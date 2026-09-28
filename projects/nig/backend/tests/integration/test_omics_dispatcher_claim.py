"""Atomic claim / concurrency guard of ``init_omics_pipeline.py``.

Runs against the real Neo4j of the test environment, including two
concurrent claims. The orchestration tests with fakes live in
``tests/unit/test_init_omics_pipeline.py``.
"""

import threading
import time
from datetime import datetime
from typing import Any, Dict, Iterator, List

import pytest
import pytz
from nig.scripts import init_omics_pipeline as dispatcher
from restapi.connectors import neo4j
from restapi.tests import FlaskClient

NOW = datetime(2026, 1, 10, tzinfo=pytz.utc)
TEST_LOCK = "omics_dispatcher_test"


class ClaimEnv:
    def __init__(self, graph: Any) -> None:
        self.graph = graph
        self.dataset_uuids: List[str] = []
        self.batch_uuids: List[str] = []

    def dataset(self, status: str = "UPLOAD COMPLETED", **properties: Any) -> str:
        node = self.graph.Dataset(
            name="omics-claim-test", status=status, **properties
        ).save()
        self.dataset_uuids.append(node.uuid)
        return str(node.uuid)

    def batch_id(self) -> str:
        uuid = f"test-batch-{len(self.batch_uuids)}-{time.time_ns()}"
        self.batch_uuids.append(uuid)
        return uuid

    def claim(
        self, sizes: Dict[str, int], max_batches: int = 1, reserved: int = 0
    ) -> List[str]:
        return dispatcher.claim_batch(
            self.graph, self.batch_id(), sizes, max_batches, reserved, NOW
        )

    def cleanup(self) -> None:
        # best effort, always run every removal
        for query, params in (
            (
                "MATCH (b:OmicsBatch) WHERE b.uuid IN $uuids DETACH DELETE b",
                {"uuids": self.batch_uuids},
            ),
            (
                "MATCH (d:Dataset) WHERE d.uuid IN $uuids DETACH DELETE d",
                {"uuids": self.dataset_uuids},
            ),
            (
                "MATCH (l:OmicsDispatcherLock {name: $name}) DELETE l",
                {"name": TEST_LOCK},
            ),
        ):
            try:
                self.graph.cypher(query, **params)
            except Exception:  # pragma: no cover
                pass


@pytest.fixture
def claim_env(client: FlaskClient, monkeypatch: Any) -> Iterator[ClaimEnv]:
    monkeypatch.setattr(dispatcher, "LOCK_NAME", TEST_LOCK)
    env = ClaimEnv(neo4j.get_instance())
    yield env
    env.cleanup()


def test_claim_creates_batch_and_queues_datasets(claim_env: ClaimEnv) -> None:
    graph = claim_env.graph
    a, b = claim_env.dataset(), claim_env.dataset()

    claimed = claim_env.claim({a: 10, b: 32})

    assert sorted(claimed) == sorted([a, b])
    batch = graph.OmicsBatch.nodes.get(uuid=claim_env.batch_uuids[0])
    assert batch.status == "PLANNED"
    assert batch.planned_bytes == 42
    assert batch.uploaded_bytes == 0
    assert batch.created == NOW
    for uuid in (a, b):
        dataset = graph.Dataset.nodes.get(uuid=uuid)
        assert dataset.status == "QUEUED"
        assert dataset.omics_status == "QUEUED"
        assert dataset.status_update == NOW
        rel = dataset.omics_batch.relationship(batch)
        assert rel.status == "QUEUED"


def test_claim_is_refused_while_a_batch_is_active(claim_env: ClaimEnv) -> None:
    a, b = claim_env.dataset(), claim_env.dataset()
    assert claim_env.claim({a: 10}) == [a]

    # max 1 active batch: a new, disjoint dataset is not claimed either
    assert claim_env.claim({b: 10}) == []

    assert claim_env.graph.Dataset.nodes.get(uuid=b).status == "UPLOAD COMPLETED"
    assert claim_env.graph.OmicsBatch.nodes.get_or_none(
        uuid=claim_env.batch_uuids[1]
    ) is None


def test_claim_rejects_stale_reserved_quota(claim_env: ClaimEnv) -> None:
    a, b = claim_env.dataset(), claim_env.dataset()
    assert claim_env.claim({a: 10}, max_batches=2) == [a]

    # planned assuming nothing reserved, but 10 bytes are reserved now
    assert claim_env.claim({b: 10}, max_batches=2, reserved=0) == []
    # planned with the current reservation: accepted
    assert claim_env.claim({b: 10}, max_batches=2, reserved=10) == [b]


def test_claim_never_takes_the_same_dataset_twice(claim_env: ClaimEnv) -> None:
    a = claim_env.dataset()
    assert claim_env.claim({a: 10}, max_batches=5) == [a]

    assert claim_env.claim({a: 10}, max_batches=5, reserved=10) == []
    assert (
        claim_env.graph.OmicsBatch.nodes.get_or_none(uuid=claim_env.batch_uuids[1])
        is None
    )


def test_claim_ignores_datasets_not_ready(claim_env: ClaimEnv) -> None:
    ready = claim_env.dataset()
    running = claim_env.dataset(status="RUNNING")

    assert claim_env.claim({ready: 10, running: 10}) == [ready]
    batch = claim_env.graph.OmicsBatch.nodes.get(uuid=claim_env.batch_uuids[0])
    assert batch.planned_bytes == 10


def test_claim_ignores_datasets_with_a_previous_task(claim_env: ClaimEnv) -> None:
    ready = claim_env.dataset()
    reset = claim_env.dataset(omics_task_id="old-remote-task")

    assert claim_env.claim({ready: 10, reset: 10}) == [ready]
    assert claim_env.graph.Dataset.nodes.get(uuid=reset).status == "UPLOAD COMPLETED"


def test_release_restores_datasets_and_frees_the_slot(claim_env: ClaimEnv) -> None:
    graph = claim_env.graph
    a = claim_env.dataset()
    assert claim_env.claim({a: 10}) == [a]
    batch_uuid = claim_env.batch_uuids[0]

    released = dispatcher.release_batch(graph, batch_uuid, "broker down", NOW)

    assert released == [a]
    dataset = graph.Dataset.nodes.get(uuid=a)
    assert dataset.status == "UPLOAD COMPLETED"
    assert dataset.omics_status is None
    batch = graph.OmicsBatch.nodes.get(uuid=batch_uuid)
    assert batch.status == "ERROR"
    assert dataset.omics_batch.relationship(batch).error_message == "broker down"
    # the ERROR batch no longer blocks the next claim
    assert claim_env.claim({a: 10}) == [a]


def test_reject_oversized_only_touches_ready_datasets(claim_env: ClaimEnv) -> None:
    graph = claim_env.graph
    ready = claim_env.dataset()
    running = claim_env.dataset(status="RUNNING")

    rejected = dispatcher.reject_oversized(graph, [ready, running], NOW)

    assert rejected == [ready]
    dataset = graph.Dataset.nodes.get(uuid=ready)
    assert dataset.status == "ERROR"
    # public message is generic, the quota detail is only technical
    assert dataset.error_message == dispatcher.USER_DATASET_TOO_LARGE
    assert dataset.omics_error_message == dispatcher.OVERSIZED_ERROR
    assert graph.Dataset.nodes.get(uuid=running).status == "RUNNING"
    # already rejected: a second run does not reject (nor notify) again
    assert dispatcher.reject_oversized(graph, [ready], NOW) == []


def test_concurrent_claims_are_serialised(claim_env: ClaimEnv) -> None:
    """Run B starts while run A holds its uncommitted claim.

    Both planned from the same state (nothing reserved, max 2 batches). Without
    the lock B would still read the datasets as ready and claim them again;
    with the lock B waits for A to commit, then sees the reservation and
    claims nothing.
    """
    graph = claim_env.graph
    a, b = claim_env.dataset(), claim_env.dataset()
    sizes = {a: 10, b: 10}
    first_id, second_id = claim_env.batch_id(), claim_env.batch_id()
    # as after the first production run: the lock node already exists
    dispatcher.ensure_lock(graph)
    a_claimed = threading.Event()
    results: Dict[str, Any] = {}

    def run_a() -> None:
        try:
            graph.db.begin()
            results["a"] = dispatcher.claim_batch(graph, first_id, sizes, 2, 0, NOW)
            a_claimed.set()
            # keep the transaction (and the lock) open while B starts
            time.sleep(1.5)
            graph.db.commit()
        except Exception as exc:  # pragma: no cover
            results["a_error"] = exc
            a_claimed.set()

    def run_b() -> None:
        a_claimed.wait(10)
        try:
            results["b_started"] = time.monotonic()
            results["b"] = dispatcher.claim_batch(graph, second_id, sizes, 2, 0, NOW)
            results["b_done"] = time.monotonic()
        except Exception as exc:  # pragma: no cover
            results["b_error"] = exc

    threads = [threading.Thread(target=run_a), threading.Thread(target=run_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert "a_error" not in results and "b_error" not in results, results
    assert sorted(results["a"]) == sorted([a, b])
    assert results["b"] == []
    # B was actually blocked by A's lock
    assert results["b_done"] - results["b_started"] > 1.0
    assert graph.OmicsBatch.nodes.get_or_none(uuid=second_id) is None
    for uuid in (a, b):
        assert len(graph.Dataset.nodes.get(uuid=uuid).omics_batch.all()) == 1
