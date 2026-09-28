"""Tests for the Omics dispatcher ``init_omics_pipeline.py``.

Orchestration (``run``/``main``) with fake graph/client/celery: no network,
no writes in ``--dry-run``. The atomic claim against the real Neo4j lives in
``tests/integration/test_omics_dispatcher_claim.py``.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz
from nig.scripts import init_omics_pipeline as dispatcher
from nig.services.omics.models import StorageUsage

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
        omics_task_id: Optional[str] = None,
    ) -> None:
        self.uuid = uuid
        self.name = uuid
        self.status = "UPLOAD COMPLETED"
        self.omics_status = omics_status
        self.omics_task_id = omics_task_id
        self.status_update = ready_at or NOW
        self.created = NOW
        study = [FakeStudy(study_type)] if study_type else []
        self.parent_study = FakeManager(study)
        self.files = FakeManager([FakeFile(s) for s in (sizes or [GB])])


@dataclass
class FakeRelation:
    status: str


class FakeMembers(FakeManager):
    def relationship(self, member: FakeRelation) -> FakeRelation:
        return member


@dataclass
class FakeBatch:
    uuid: str
    planned_bytes: int = 0
    uploaded_bytes: int = 0
    created: datetime = NOW
    stale_notified_at: Optional[datetime] = None
    saves: int = 0
    status: str = "RUNNING"
    # SENT_TO_OMICS statuses of its members: by default still open
    relation_statuses: List[str] = field(default_factory=lambda: ["RUNNING"])

    @property
    def datasets(self) -> FakeMembers:
        return FakeMembers([FakeRelation(s) for s in self.relation_statuses])

    def save(self) -> "FakeBatch":
        self.saves += 1
        return self


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
    stale_task = FakeDataset("reset", omics_status="ERROR", omics_task_id="t-old")

    selected = dispatcher.select_omics_datasets(
        [genome, exome, orphan, in_flight, failed_before, stale_task]
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


def test_run_closes_orphan_batches_and_frees_the_slot() -> None:
    # every dataset deleted, or all relations closed without a final event
    emptied = FakeBatch("emptied", relation_statuses=[])
    released = FakeBatch("released", relation_statuses=["UPLOAD COMPLETED"])
    graph = FakeGraph([FakeDataset("a")], batches=[emptied, released])
    sender = Sender()

    report = dispatcher.run(
        graph,
        FakeClient(),
        settings(max_concurrent_batches=1),
        dry_run=False,
        now=NOW,
        send_task=sender,
    )

    assert report["finalized_batches"] == {"emptied": "ERROR", "released": "PARTIAL"}
    assert emptied.status == "ERROR" and emptied.saves == 1
    assert released.status == "PARTIAL" and released.saves == 1
    assert report["active_batches"] == []
    assert report["batch"]["datasets"] == ["a"]


def test_dry_run_reports_orphan_batches_without_closing_them() -> None:
    emptied = FakeBatch("emptied", relation_statuses=[])

    report = dispatcher.run(
        ReadOnlyGraph([], batches=[emptied]),
        FakeClient(),
        settings(),
        dry_run=True,
        now=NOW,
        send_task=Sender(),
    )

    assert report["finalized_batches"] == {"emptied": "ERROR"}
    assert emptied.status == "RUNNING" and emptied.saves == 0


def test_uncertain_submit_keeps_holding_the_slot() -> None:
    held = FakeBatch("held", relation_statuses=["COMPLETED", "SUBMIT_UNKNOWN"])
    graph = FakeGraph([FakeDataset("a")], batches=[held])

    report = dispatcher.run(
        graph, FakeClient(), settings(), dry_run=False, now=NOW, send_task=Sender()
    )

    assert report["finalized_batches"] == {}
    assert report["skipped_reason"] == "max concurrent batches reached"
    assert held.status == "RUNNING"


def test_run_warns_about_stale_batches(monkeypatch: Any) -> None:
    stale = FakeBatch("stuck", created=NOW - timedelta(hours=100))
    graph = FakeGraph([], batches=[stale])
    notifications: List[Any] = []
    monkeypatch.setattr(
        dispatcher,
        "notify_stale_batch",
        lambda batch, hours: notifications.append((batch.uuid, hours)),
    )

    report = dispatcher.run(
        graph, FakeClient(), settings(), dry_run=False, now=NOW, send_task=Sender()
    )

    assert report["stale_batches"] == ["stuck"]
    assert notifications == [("stuck", 48)]
    assert stale.stale_notified_at == NOW

    # next dispatcher runs within the window: still reported, not re-notified
    for hours in (1, 47):
        dispatcher.run(
            graph,
            FakeClient(),
            settings(),
            dry_run=False,
            now=NOW + timedelta(hours=hours),
            send_task=Sender(),
        )
    assert notifications == [("stuck", 48)]

    # a full window later: reminded once more
    later = NOW + timedelta(hours=48)
    dispatcher.run(
        graph, FakeClient(), settings(), dry_run=False, now=later, send_task=Sender()
    )
    assert notifications == [("stuck", 48), ("stuck", 48)]
    assert stale.stale_notified_at == later


def test_dry_run_does_not_notify_stale_batches(monkeypatch: Any) -> None:
    stale = FakeBatch("stuck", created=NOW - timedelta(hours=100))
    notifications: List[Any] = []
    monkeypatch.setattr(
        dispatcher, "notify_stale_batch", lambda b, h: notifications.append(b)
    )

    report = dispatcher.run(
        FakeGraph([], batches=[stale]),
        FakeClient(),
        settings(),
        dry_run=True,
        now=NOW,
        send_task=Sender(),
    )

    assert report["stale_batches"] == ["stuck"]
    assert notifications == []
    assert stale.stale_notified_at is None
    assert stale.saves == 0


def test_failed_stale_notification_is_retried(monkeypatch: Any) -> None:
    stale = FakeBatch("stuck", created=NOW - timedelta(hours=100))

    def fail(batch: Any, hours: int) -> None:
        raise RuntimeError("smtp down")

    monkeypatch.setattr(dispatcher, "notify_stale_batch", fail)
    dispatcher.run(
        FakeGraph([], batches=[stale]),
        FakeClient(),
        settings(),
        dry_run=False,
        now=NOW,
        send_task=Sender(),
    )

    assert stale.stale_notified_at is None


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
