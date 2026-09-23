"""Tests for Omics status polling and result retrieval with fake clients."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import pytz
from nig.services.omics.models import TaskInfo
from nig.tasks import omics_fetch_results as fetch
from nig.tasks import omics_poll_tasks as poll

NOW = datetime(2026, 1, 10, tzinfo=pytz.utc)


class Manager:
    def __init__(self, values: List[Any]) -> None:
        self.values = values

    def all(self) -> List[Any]:
        return list(self.values)

    def single(self) -> Any:
        return self.values[0] if self.values else None


class Relation:
    def __init__(self) -> None:
        self.status = "RUNNING"
        self.error_message: Optional[str] = None

    def save(self) -> None:
        pass


class Batch:
    def __init__(self) -> None:
        self.status = "RUNNING"
        self.datasets = Manager([])

    def save(self) -> None:
        pass


class Dataset:
    def __init__(self, uuid: str, remote_task: str = "task-1") -> None:
        self.uuid = uuid
        self.name = uuid
        self.omics_task_id = remote_task
        self.omics_status = "RUNNING"
        self.status = "RUNNING"
        self.omics_error_message = None
        self.error_message = None
        self.parent_study = Manager([type("Study", (), {"uuid": "s", "name": "S"})()])
        self._batch = Batch()
        self._batch.datasets.values = [self]
        self.omics_batch = type(
            "BatchLinks",
            (), {"all": lambda _: [self._batch], "relationship": lambda _, __: Relation()},
        )()
        self.saves = 0

    def save(self) -> None:
        self.saves += 1


class Nodes:
    def __init__(self, datasets: List[Dataset]) -> None:
        self.datasets = {d.uuid: d for d in datasets}

    def filter(self, **kwargs: Any) -> "Nodes":
        assert kwargs == {"omics_task_id__isnull": False}
        return self

    def all(self) -> List[Dataset]:
        return list(self.datasets.values())

    def get_or_none(self, uuid: str) -> Optional[Dataset]:
        return self.datasets.get(uuid)


class Graph:
    def __init__(self, datasets: List[Dataset]) -> None:
        self.Dataset = type("DatasetModel", (), {"nodes": Nodes(datasets)})()
        self._artifacts: Dict[str, Any] = {}
        self.OmicsArtifact = type(
            "ArtifactModel",
            (),
            {
                "nodes": type(
                    "ArtifactNodes",
                    (), {
                        "get_or_none": lambda _, remote_file_id: self._artifacts.get(
                            remote_file_id
                        )
                    },
                )(),
                "__call__": lambda _, **kwargs: Artifact(self._artifacts, **kwargs),
            },
        )()


class Artifact:
    def __init__(self, registry: Dict[str, Any], **kwargs: Any) -> None:
        self._registry = registry
        self.remote_file_id = kwargs["remote_file_id"]
        self.name = kwargs["name"]
        self.dataset = type("DatasetLink", (), {"connect": lambda _, dataset: None})()

    def save(self) -> "Artifact":
        self._registry[self.remote_file_id] = self
        return self


class PollClient:
    def __init__(self, statuses: Dict[str, str]) -> None:
        self.statuses = statuses

    def get_task(self, task_id: str) -> TaskInfo:
        return TaskInfo(task_id=task_id, status=self.statuses[task_id])


@pytest.fixture(autouse=True)
def no_mail(monkeypatch: Any) -> None:
    monkeypatch.setattr(poll, "_notify_error", lambda dataset, message: None)


def test_poll_transitions_processing_and_complete_and_dispatches_fetch() -> None:
    processing, complete = Dataset("processing"), Dataset("complete")
    calls: List[str] = []

    report = poll.poll_tasks(
        Graph([processing, complete]),
        PollClient({"task-1": "Processing"}),
        send_task=lambda uuid: calls.append(uuid) or "fetch-task",
        now=NOW,
    )

    assert report["running"] == ["processing", "complete"]
    assert complete.omics_status == "RUNNING"
    assert calls == []

    complete.omics_task_id = "task-2"
    report = poll.poll_tasks(
        Graph([complete]),
        PollClient({"task-2": "Complete"}),
        send_task=lambda uuid: calls.append(uuid) or "fetch-task",
        now=NOW,
    )

    assert report["fetching"] == ["complete"]
    assert complete.omics_status == "FETCHING"
    assert calls == ["complete"]


def test_poll_remote_error_marks_dataset_error() -> None:
    dataset = Dataset("failed")

    report = poll.poll_tasks(
        Graph([dataset]), PollClient({"task-1": "Error"}), now=NOW
    )

    assert report["failed"] == ["failed"]
    assert dataset.status == dataset.omics_status == "ERROR"
    assert "remote task reported Error" in dataset.error_message


def test_poll_does_not_mark_fetching_when_dispatch_fails() -> None:
    dataset = Dataset("complete")

    report = poll.poll_tasks(
        Graph([dataset]),
        PollClient({"task-1": "Complete"}),
        send_task=lambda uuid: (_ for _ in ()).throw(RuntimeError("broker down")),
        now=NOW,
    )

    assert report["fetching"] == []
    assert dataset.omics_status == "RUNNING"


def test_fetch_skips_non_fetching_dataset() -> None:
    dataset = Dataset("d1")
    graph = Graph([dataset])

    assert fetch.fetch_results(graph, object(), "d1", NOW) == {
        "downloaded": [],
        "skipped": True,
    }


class FetchClient:
    def __init__(self, remains_remote: bool = False) -> None:
        self.remains_remote = remains_remote

    def get_task_files(self, task_id: str) -> List[Dict[str, Any]]:
        return [
            {"_kind": "gvcf", "file_id": "g", "user_filename": "a.g.vcf.gz", "size": 3},
            {"_kind": "tbi", "file_id": "t", "user_filename": "a.g.vcf.gz.tbi", "size": 3},
            {"_kind": "bam", "file_id": "b", "user_filename": "a.bam", "size": 3},
        ]

    def download_file(self, file_id: str, destination: Path, expected_size: int) -> Path:
        destination.write_bytes(b"abc")
        return destination

    def list_uploaded_files(self) -> List[Dict[str, str]]:
        return [{"file_id": "g"}] if self.remains_remote else []


def test_fetch_persists_downloaded_outputs_and_completes_dataset(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dataset = Dataset("d1")
    dataset.omics_status = "FETCHING"
    graph = Graph([dataset])
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)

    report = fetch.fetch_results(graph, FetchClient(), "d1", NOW)

    assert report == {"downloaded": ["g", "t", "b"], "cleanup_pending": False}
    assert dataset.status == dataset.omics_status == "COMPLETED"
    assert {artifact.kind for artifact in graph._artifacts.values()} == {"GVCF", "TBI", "BAM"}
    assert all(artifact.status == "DOWNLOADED" for artifact in graph._artifacts.values())


def test_fetch_marks_cleanup_pending_when_outputs_remain_remote(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dataset = Dataset("d1")
    dataset.omics_status = "FETCHING"
    graph = Graph([dataset])
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)

    report = fetch.fetch_results(graph, FetchClient(remains_remote=True), "d1", NOW)

    assert report["cleanup_pending"] is True
    assert dataset.omics_status == "CLEANUP PENDING"
    assert dataset.status == "RUNNING"
