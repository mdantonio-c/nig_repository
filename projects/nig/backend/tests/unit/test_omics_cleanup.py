"""Tests for conservative Omics storage reconciliation."""

import inspect
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz
from nig.services.omics.models import StorageUsage
from nig.tasks import omics_cleanup as cleanup
from nig.tasks.omics_cleanup import reconcile, registered_remote_names

NOW = datetime(2026, 1, 10, tzinfo=pytz.utc)
OLD = (NOW - timedelta(hours=100)).isoformat()
RECENT = (NOW - timedelta(hours=1)).isoformat()


class Manager:
    def __init__(self, values: List[Any]) -> None:
        self.values = values

    def all(self) -> List[Any]:
        return list(self.values)

    def single(self) -> Any:
        return self.values[0] if self.values else None


class NodeSet(Manager):
    def filter(self, **kwargs: Any) -> "NodeSet":
        ((key, isnull),) = kwargs.items()
        field = key.replace("__isnull", "")
        return NodeSet([v for v in self.values if (getattr(v, field) is None) == isnull])


class Dataset:
    def __init__(self, uuid: str, status: str, updated: datetime = NOW) -> None:
        self.uuid = uuid
        self.status = status
        self.status_update = updated


class File:
    # Omics ids are re-encrypted on every response: NIG matches remote
    # storage by filename (dataset-uuid-prefixed), never by file_id.
    def __init__(self, remote_id: Optional[str], name: str, dataset: Any) -> None:
        self.omics_file_id = remote_id
        self.name = name
        self.dataset = Manager([dataset] if dataset else [])


class Artifact:
    def __init__(self, remote_id: Optional[str], name: str, dataset: Any) -> None:
        self.remote_file_id = remote_id
        self.name = name
        self.dataset = Manager([dataset] if dataset else [])


def model(nodes: List[Any]) -> Any:
    return type("Model", (), {"nodes": NodeSet(nodes)})()


ACTIVE = Dataset("ds-active", "RUNNING")
DONE_RECENT = Dataset("ds-done-recent", "COMPLETED", NOW - timedelta(hours=1))
DONE_OLD = Dataset("ds-done-old", "ERROR", NOW - timedelta(hours=100))


class Graph:
    def __init__(self) -> None:
        self.File = model(
            [
                File("input-active", "input-active.fastq.gz", ACTIVE),
                File("input-done-old", "input-done-old.fastq.gz", DONE_OLD),
                File(None, "input-pending.fastq.gz", ACTIVE),
            ]
        )
        self.OmicsArtifact = model(
            [
                Artifact("output-done-recent", "output-done-recent.g.vcf.gz", DONE_RECENT),
                Artifact("output-deleted-dataset", "output-deleted-dataset.g.vcf.gz", None),
            ]
        )


class Client:
    def __init__(self, remote: Optional[List[Dict[str, Any]]] = None) -> None:
        self.deleted: List[str] = []
        self.remote = remote if remote is not None else [
            {
                "file_id": "input-active",
                "user_filename": f"{ACTIVE.uuid}_input-active.fastq.gz",
                "size": 1,
                "date": OLD,
            },
            {
                "file_id": "input-done-old",
                "user_filename": f"{DONE_OLD.uuid}_input-done-old.fastq.gz",
                "size": 2,
                "date": OLD,
            },
            {
                "file_id": "output-done-recent",
                "user_filename": "output-done-recent.g.vcf.gz",
                "size": 4,
                "date": OLD,
            },
            {
                "file_id": "output-deleted-dataset",
                "user_filename": "output-deleted-dataset.g.vcf.gz",
                "size": 8,
                "date": OLD,
            },
            {
                "file_id": "unknown-old-0123456789",
                "user_filename": "unknown-old.fastq.gz",
                "size": 16,
                "date": OLD,
            },
            {
                "file_id": "unknown-recent",
                "user_filename": "unknown-recent.fastq.gz",
                "size": 32,
                "date": RECENT,
            },
            {"file_id": "unknown-undated", "user_filename": "unknown-undated.fastq.gz", "size": 64},
            {
                "file_id": "unknown-bad-date",
                "user_filename": "unknown-bad-date.fastq.gz",
                "size": 128,
                "date": "yesterday",
            },
            {"size": 256},
        ]

    def list_uploaded_files(self) -> List[Dict[str, Any]]:
        return self.remote

    @staticmethod
    def get_storage_usage() -> StorageUsage:
        return StorageUsage(usage=10, quota=100, limit=0.1, can_upload=True)

    def delete_file(self, remote_id: str) -> bool:
        self.deleted.append(remote_id)
        return True


def test_registered_names_include_tracked_inputs_and_artifacts() -> None:
    assert registered_remote_names(Graph()) == {
        "ds-active_input-active.fastq.gz",
        "ds-done-old_input-done-old.fastq.gz",
        "output-done-recent.g.vcf.gz",
        "output-deleted-dataset.g.vcf.gz",
    }



def test_reconcile_classifies_remote_storage_with_ttl() -> None:
    report = reconcile(Graph(), Client(), orphan_ttl_hours=72, now=NOW)
    categories = report["categories"]

    counts = {name: value["count"] for name, value in categories.items()}
    assert counts == {
        "orphan_candidates": 1,
        "unknown_recent": 3,
        "cleanup_not_observed": 2,
        "terminal_recent": 1,
        "known_active": 1,
    }
    assert categories["orphan_candidates"]["bytes"] == 16
    assert categories["unknown_recent"]["bytes"] == 32 + 64 + 128
    assert categories["cleanup_not_observed"]["bytes"] == 2 + 8
    assert report["remote_count"] == 8
    assert report["storage"]["usage"] == 10


def test_a_longer_ttl_protects_old_objects() -> None:
    report = reconcile(Graph(), Client(), orphan_ttl_hours=200, now=NOW)

    categories = report["categories"]
    assert categories["orphan_candidates"]["count"] == 0
    assert categories["unknown_recent"]["count"] == 4
    assert categories["terminal_recent"]["count"] == 2
    # a registered object whose dataset no longer exists is always reported
    assert categories["cleanup_not_observed"]["count"] == 1


def test_report_never_contains_full_remote_ids() -> None:
    report = reconcile(Graph(), Client(), now=NOW)

    text = str(report)
    for item in Client().remote:
        if "file_id" in item:
            assert item["file_id"] not in text
    assert report["categories"]["orphan_candidates"]["sample_ids"] == [
        cleanup._obscure("unknown-old-0123456789")
    ]


def test_sample_ids_are_capped() -> None:
    remote = [{"file_id": f"orphan-{i:04d}", "date": OLD} for i in range(50)]

    report = reconcile(Graph(), Client(remote), now=NOW)

    orphans = report["categories"]["orphan_candidates"]
    assert orphans["count"] == 50
    assert len(orphans["sample_ids"]) == cleanup.MAX_SAMPLE_IDS


def test_reconcile_is_report_only_even_when_delete_is_requested() -> None:
    client = Client()

    report = reconcile(Graph(), client, delete=True, now=NOW)

    assert report["deleted"] == 0
    assert report["delete_requested"] is True
    assert client.deleted == []


def test_cleanup_does_nothing_when_omics_is_disabled(monkeypatch: Any) -> None:
    calls: List[str] = []
    monkeypatch.setattr(cleanup, "omics_enabled", lambda: False)
    monkeypatch.setattr(cleanup, "reconcile", lambda *a, **k: calls.append("run"))
    monkeypatch.setattr(cleanup, "client_from_env", lambda: calls.append("client"))

    inspect.unwrap(cleanup.omics_cleanup.__wrapped__)(None)

    assert calls == []
