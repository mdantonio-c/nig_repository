"""Tests for the Omics dispatcher ``init_omics_pipeline.py``.

* orchestration (``run``/``main``) with fake graph/client/celery: no network,
  no writes in ``--dry-run``;
* atomic claim / concurrency guard against the real Neo4j of
  the test environment, including two concurrent claims.
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional

import pytest
import pytz
from nig.scripts import init_omics_pipeline as dispatcher
from nig.services.omics.models import StorageUsage
from restapi.connectors import neo4j
from restapi.tests import FlaskClient

NOW = datetime(2026, 1, 10, tzinfo=pytz.utc)
GB = 1_000_000_000


# -- fakes ------------------------------------------------------------------


class FakeStudy:
    def __init__(self, study_type: Optional[str]) -> None:
        self.study_type = study_type
        self.uuid = f"study-{study_type}"
        self.name = f"Study {study_type}"


class FakeManager:
    def __init__(self, items: List[Any]) -> None:
        self._items = items

    def single(self) -> Any:
        return self._items[0] if self._items else None

    def all(self) -> List[Any]:
        return list(self._items)


@dataclass
class FakeFile:
    size: Optional[int]


class FakeDataset:
    def __init__(
        self,
        uuid: str,
        study_type: Optional[str] = "genome",
        sizes: Optional[List[Optional[int]]] = None,
        ready_at: Optional[datetime] = None,
        omics_status: Optional[str] = None,
    ) -> None:
        self.uuid = uuid
        self.name = uuid
        self.status = "UPLOAD COMPLETED"
        self.omics_status = omics_status
        self.status_update = ready_at or NOW
        self.created = NOW
        study = [FakeStudy(study_type)] if study_type else []
        self.parent_study = FakeManager(study)
        self.files = FakeManager([FakeFile(s) for s in (sizes or [GB])])


@dataclass
class FakeBatch:
    uuid: str
    planned_bytes: int = 0
    uploaded_bytes: int = 0
    created: datetime = NOW


class FakeNodeSet:
    def __init__(self, nodes: List[Any]) -> None:
        self._nodes = nodes

    def filter(self, **kwargs: Any) -> "FakeNodeSet":
        return self

    def all(self) -> List[Any]:
        return list(self._nodes)

    def get_or_none(self, **kwargs: Any) -> Any:
        return next((n for n in self._nodes if n.uuid == kwargs.get("uuid")), None)


class FakeModel:
    def __init__(self, nodes: List[Any]) -> None:
        self.nodes = FakeNodeSet(nodes)


class FakeGraph:
    def __init__(
        self, datasets: List[Any], batches: Optional[List[Any]] = None
    ) -> None:
        self.Dataset = FakeModel(datasets)
        self.OmicsBatch = FakeModel(batches or [])
        self.queries: List[Dict[str, Any]] = []

    def cypher(self, query: str, **params: Any) -> List[List[str]]:
        self.queries.append({"query": query, **params})
        if query is dispatcher.CLAIM_QUERY:
            return [[u] for u in params["dataset_uuids"]]
        if query is dispatcher.REJECT_QUERY:
            return [[u] for u in params["dataset_uuids"]]
        return []

    def called(self, query: str) -> List[Dict[str, Any]]:
        return [q for q in self.queries if q["query"] is query]


class ReadOnlyGraph(FakeGraph):
    def cypher(self, query: str, **params: Any) -> List[List[str]]:
        raise AssertionError("dry-run must not write to Neo4j")


@dataclass
class FakeClient:
    usage: StorageUsage = field(
        default_factory=lambda: StorageUsage(
            usage=0, quota=100 * GB, limit=0.0, can_upload=True
        )
    )
    calls: int = 0

    def get_storage_usage(self) -> StorageUsage:
        self.calls += 1
        return self.usage


def settings(**overrides: Any) -> dispatcher.DispatcherSettings:
    values: Dict[str, Any] = dict(
        enabled=True,
        api_url="https://omics.invalid/api/v1/",
        username="user",
        password="secret",
        request_timeout=5,
        expected_quota_bytes=100 * GB,
        safety_margin_pct=5,
        max_concurrent_batches=1,
        batch_stale_hours=48,
    )
    values.update(overrides)
    return dispatcher.DispatcherSettings(**values)


class Sender:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: List[Any] = []

    def __call__(self, batch_uuid: str, dataset_uuids: List[str]) -> str:
        self.calls.append((batch_uuid, dataset_uuids))
        if self.fail:
            raise RuntimeError("broker down")
        return "task-1"


def test_send_run_batch_uses_the_batch_uuid_as_celery_task_id(monkeypatch: Any) -> None:
    calls: List[Dict[str, Any]] = []

    class FakeCeleryApp:
        @staticmethod
        def send_task(*args: Any, **kwargs: Any) -> Any:
            calls.append({"args": args, "kwargs": kwargs})
            return type("TaskResult", (), {"id": "batch-1"})()

    monkeypatch.setattr(
        dispatcher.celery,
        "get_instance",
        lambda: type("Connector", (), {"celery_app": FakeCeleryApp()})(),
    )

    assert dispatcher.send_run_batch("batch-1", ["dataset-1"]) == "batch-1"
    assert calls[0]["args"] == (dispatcher.RUN_BATCH_TASK,)
    assert calls[0]["kwargs"]["task_id"] == "batch-1"


# -- selection --------------------------------------------------------------


def test_select_omics_datasets_keeps_only_idle_genome_datasets() -> None:
    genome = FakeDataset("genome")
    exome = FakeDataset("exome", study_type="exome")
    orphan = FakeDataset("orphan", study_type=None)
    in_flight = FakeDataset("in-flight", omics_status="RUNNING")
    failed_before = FakeDataset("retry", omics_status="ERROR")

    selected = dispatcher.select_omics_datasets(
        [genome, exome, orphan, in_flight, failed_before]
    )

    assert selected == [genome, failed_before]


def test_build_candidates_sums_file_sizes_and_skips_unknown_sizes() -> None:
    ok = FakeDataset("ok", sizes=[3, 4])
    no_files = FakeDataset("empty")
    no_files.files = FakeManager([])
    missing_size = FakeDataset("missing", sizes=[3, None])

    candidates, invalid = dispatcher.build_candidates([ok, no_files, missing_size])

    assert [(c.uuid, c.size_bytes) for c in candidates] == [("ok", 7)]
    assert invalid == ["empty", "missing"]


def test_reserved_bytes_counts_only_not_yet_uploaded_bytes() -> None:
    batches = [
        FakeBatch("a", planned_bytes=10, uploaded_bytes=4),
        FakeBatch("b", planned_bytes=5, uploaded_bytes=9),
    ]

    assert dispatcher.reserved_bytes(batches) == 6


def test_find_stale_batches() -> None:
    batches = [
        FakeBatch("fresh", created=NOW - timedelta(hours=1)),
        FakeBatch("stale", created=NOW - timedelta(hours=49)),
    ]

    assert dispatcher.find_stale_batches(batches, NOW, 48) == ["stale"]


# -- run() orchestration ----------------------------------------------------


def test_dry_run_plans_without_writing_or_sending() -> None:
    graph = ReadOnlyGraph(
        [
            FakeDataset("a", sizes=[40 * GB], ready_at=NOW - timedelta(hours=2)),
            FakeDataset("b", sizes=[40 * GB], ready_at=NOW - timedelta(hours=1)),
            FakeDataset("c", sizes=[200 * GB]),
            FakeDataset("exome", study_type="exome"),
        ]
    )
    sender = Sender()

    report = dispatcher.run(
        graph, FakeClient(), settings(), dry_run=True, now=NOW, send_task=sender
    )

    assert report["dry_run"] is True
    assert report["plan"]["selected"] == ["a", "b"]
    assert report["plan"]["oversized"] == ["c"]
    assert report["batch"] is None
    assert sender.calls == []


def test_run_skips_when_max_concurrent_batches_reached() -> None:
    graph = FakeGraph([FakeDataset("a")], batches=[FakeBatch("busy")])
    client = FakeClient()
    sender = Sender()

    report = dispatcher.run(
        graph, client, settings(), dry_run=False, now=NOW, send_task=sender
    )

    assert report["skipped_reason"] == "max concurrent batches reached"
    assert client.calls == 0
    assert graph.queries == []
    assert sender.calls == []


def test_run_warns_about_stale_batches() -> None:
    stale = FakeBatch("stuck", created=NOW - timedelta(hours=100))
    graph = FakeGraph([], batches=[stale])
    notifications: List[Any] = []

    original = dispatcher.notify_stale_batch
    dispatcher.notify_stale_batch = lambda batch, hours: notifications.append(
        (batch.uuid, hours)
    )
    try:
        report = dispatcher.run(
            graph, FakeClient(), settings(), dry_run=True, now=NOW, send_task=Sender()
        )
    finally:
        dispatcher.notify_stale_batch = original

    assert report["stale_batches"] == ["stuck"]
    assert notifications == [("stuck", 48)]


def test_run_skips_without_ready_genome_datasets() -> None:
    client = FakeClient()
    graph = FakeGraph([FakeDataset("exome", study_type="exome")])

    report = dispatcher.run(
        graph, client, settings(), dry_run=False, now=NOW, send_task=Sender()
    )

    assert report["skipped_reason"] == "no genome datasets ready"
    assert client.calls == 0


def test_run_skips_when_remote_refuses_uploads() -> None:
    client = FakeClient(
        StorageUsage(usage=0, quota=100 * GB, limit=0.0, can_upload=False)
    )
    graph = FakeGraph([FakeDataset("a")])
    sender = Sender()

    report = dispatcher.run(
        graph, client, settings(), dry_run=False, now=NOW, send_task=sender
    )

    assert report["skipped_reason"] == "remote storage does not accept uploads"
    assert graph.queries == []
    assert sender.calls == []


def test_run_falls_back_to_expected_quota() -> None:
    client = FakeClient(StorageUsage(usage=0, quota=0, limit=0.0, can_upload=True))
    graph = FakeGraph([FakeDataset("a", sizes=[10 * GB])])

    report = dispatcher.run(
        graph,
        client,
        settings(expected_quota_bytes=20 * GB),
        dry_run=True,
        now=NOW,
        send_task=Sender(),
    )

    assert report["plan"]["capacity_bytes"] == 19 * GB
    assert report["plan"]["selected"] == ["a"]


def test_run_includes_quota_reserved_by_active_batches() -> None:
    # 60 GB still to be uploaded by the active batch: only 35 GB usable
    active = FakeBatch("active", planned_bytes=60 * GB, uploaded_bytes=0)
    graph = FakeGraph(
        [
            FakeDataset("fits", sizes=[30 * GB], ready_at=NOW - timedelta(hours=1)),
            FakeDataset("waits", sizes=[40 * GB], ready_at=NOW - timedelta(hours=2)),
        ],
        batches=[active],
    )
    sender = Sender()

    report = dispatcher.run(
        graph,
        FakeClient(),
        settings(max_concurrent_batches=2),
        dry_run=False,
        now=NOW,
        send_task=sender,
    )

    assert report["reserved_bytes"] == 60 * GB
    assert report["plan"]["selected"] == ["fits"]
    assert report["plan"]["deferred"] == ["waits"]
    (claim,) = graph.called(dispatcher.CLAIM_QUERY)
    assert claim["expected_reserved"] == 60 * GB
    assert claim["max_batches"] == 2
    assert claim["sizes"] == {"fits": 30 * GB}


def test_run_claims_sends_task_and_rejects_oversized(monkeypatch: Any) -> None:
    notified: List[str] = []
    monkeypatch.setattr(
        dispatcher, "notify_oversized", lambda graph, uuid: notified.append(uuid)
    )
    graph = FakeGraph(
        [FakeDataset("a", sizes=[10 * GB]), FakeDataset("huge", sizes=[500 * GB])]
    )
    sender = Sender()

    report = dispatcher.run(
        graph, FakeClient(), settings(), dry_run=False, now=NOW, send_task=sender
    )

    assert report["rejected_datasets"] == ["huge"]
    assert notified == ["huge"]
    batch_uuid = report["batch"]["uuid"]
    assert report["batch"]["datasets"] == ["a"]
    assert sender.calls == [(batch_uuid, ["a"])]
    (claim,) = graph.called(dispatcher.CLAIM_QUERY)
    assert claim["holder"] == batch_uuid
    assert graph.called(dispatcher.RELEASE_QUERY) == []


def test_run_does_not_send_when_claim_is_lost() -> None:
    class LostClaimGraph(FakeGraph):
        def cypher(self, query: str, **params: Any) -> List[List[str]]:
            super().cypher(query, **params)
            return []

    graph = LostClaimGraph([FakeDataset("a")])
    sender = Sender()

    report = dispatcher.run(
        graph, FakeClient(), settings(), dry_run=False, now=NOW, send_task=sender
    )

    assert report["skipped_reason"].startswith("state changed")
    assert sender.calls == []


def test_run_releases_claim_when_task_cannot_be_sent() -> None:
    graph = FakeGraph([FakeDataset("a")])

    report = dispatcher.run(
        graph,
        FakeClient(),
        settings(),
        dry_run=False,
        now=NOW,
        send_task=Sender(fail=True),
    )

    assert report["batch"] is None
    assert report["skipped_reason"] == "task submission failed, claim released"
    (claim,) = graph.called(dispatcher.CLAIM_QUERY)
    (release,) = graph.called(dispatcher.RELEASE_QUERY)
    assert release["holder"] == claim["holder"]


# -- main() -----------------------------------------------------------------


class ExplodingNeo4j:
    @staticmethod
    def get_instance() -> Any:
        raise AssertionError("Neo4j must not be touched")


def patch_settings(monkeypatch: Any, **overrides: Any) -> None:
    # restapi Env caches values (lru_cache): patch the settings, not os.environ
    monkeypatch.setattr(
        dispatcher.DispatcherSettings,
        "from_env",
        classmethod(lambda cls: settings(**overrides)),
    )


def test_main_exits_immediately_when_feature_flag_is_off(monkeypatch: Any) -> None:
    patch_settings(monkeypatch, enabled=False)
    monkeypatch.setattr(dispatcher, "neo4j", ExplodingNeo4j)

    assert dispatcher.main(["--dry-run"]) == 0


def test_main_requires_credentials_when_enabled(monkeypatch: Any) -> None:
    patch_settings(monkeypatch, username="", password="")
    monkeypatch.setattr(dispatcher, "neo4j", ExplodingNeo4j)

    assert dispatcher.main(["--dry-run"]) == 1


def test_settings_defaults_match_the_plan() -> None:
    # nothing OMICS_* is configured in the test container
    defaults = dispatcher.DispatcherSettings.from_env()

    assert defaults.enabled is False
    assert defaults.expected_quota_bytes == 1_000_000_000_000
    assert defaults.safety_margin_pct == 5
    assert defaults.max_concurrent_batches == 1
    assert defaults.batch_stale_hours == 48


# -- atomic claim against the real Neo4j ------------------------------------

TEST_LOCK = "omics_dispatcher_test"


class ClaimEnv:
    def __init__(self, graph: Any) -> None:
        self.graph = graph
        self.dataset_uuids: List[str] = []
        self.batch_uuids: List[str] = []

    def dataset(self, status: str = "UPLOAD COMPLETED") -> str:
        node = self.graph.Dataset(name="omics-claim-test", status=status).save()
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
    assert dataset.error_message == dispatcher.OVERSIZED_ERROR
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
