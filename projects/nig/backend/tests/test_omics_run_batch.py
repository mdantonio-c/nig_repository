"""Tests for Omics batch execution with an entirely mocked remote client."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import pytz
from nig.services.omics.errors import OmicsQuotaExceeded, OmicsRequestError
from nig.tasks import omics_run_batch as task

NOW = datetime(2026, 1, 10, tzinfo=pytz.utc)


class Manager:
    def __init__(self, values: List[Any]) -> None:
        self.values = values

    def all(self) -> List[Any]:
        return list(self.values)

    def single(self) -> Any:
        return self.values[0] if self.values else None


@dataclass
class Relation:
    status: str = "QUEUED"
    error_message: Optional[str] = None
    saves: int = 0

    def save(self) -> None:
        self.saves += 1


class Dataset:
    def __init__(self, uuid: str, files: List[Any]) -> None:
        self.uuid = uuid
        self.name = uuid
        self.files = Manager(files)
        self.status = "QUEUED"
        self.omics_status = "QUEUED"
        self.omics_task_id: Optional[str] = None
        self.omics_error_message: Optional[str] = None
        self.error_message: Optional[str] = None
        self.status_update: Optional[datetime] = None
        self.omics_status_update: Optional[datetime] = None
        self.parent_study = Manager([type("Study", (), {"uuid": "study", "name": "Study"})()])
        self._relation = Relation()
        self.saves = 0

    def save(self) -> None:
        self.saves += 1

    @property
    def omics_batch(self) -> Any:
        return type("BatchRelation", (), {"relationship": lambda _, __: self._relation})()


class File:
    def __init__(self, name: str, size: int = 10) -> None:
        self.name = name
        self.size = size
        self.omics_file_id: Optional[str] = None
        self.omics_uploaded_at: Optional[datetime] = None
        self.omics_status: Optional[str] = None
        self.saves = 0

    def save(self) -> None:
        self.saves += 1


class NodeSet:
    def __init__(self, values: Dict[str, Any]) -> None:
        self.values = values

    def get_or_none(self, uuid: str) -> Any:
        return self.values.get(uuid)


class Model:
    def __init__(self, values: Dict[str, Any]) -> None:
        self.nodes = NodeSet(values)


class Batch:
    def __init__(self, uuid: str) -> None:
        self.uuid = uuid
        self.status = "PLANNED"
        self.planned_bytes = 100
        self.uploaded_bytes = 0
        self.saves = 0

    def save(self) -> None:
        self.saves += 1


class Graph:
    def __init__(self, batch: Batch, datasets: List[Dataset]) -> None:
        self.OmicsBatch = Model({batch.uuid: batch})
        self.Dataset = Model({dataset.uuid: dataset for dataset in datasets})


class Client:
    def __init__(self, uploads: Optional[List[Any]] = None, submit: Optional[Any] = None) -> None:
        self.uploads = list(uploads or [])
        self.submit = submit if submit is not None else {"task_id": "remote-task"}
        self.uploaded: List[Path] = []
        self.deleted: List[str] = []
        self.submits: List[Any] = []

    def upload_file(self, path: Path, tags: List[str]) -> str:
        self.uploaded.append(path)
        result = self.uploads.pop(0) if self.uploads else f"remote-{path.name}"
        if isinstance(result, Exception):
            raise result
        return result

    def delete_file(self, file_id: str) -> bool:
        self.deleted.append(file_id)
        return True

    def submit_nig_germline(self, input_ids: List[str], **kwargs: Any) -> Dict[str, str]:
        self.submits.append((input_ids, kwargs))
        if isinstance(self.submit, Exception):
            raise self.submit
        return self.submit


@pytest.fixture(autouse=True)
def input_files(monkeypatch: Any, tmp_path: Path) -> Path:
    def path_for(dataset: Dataset) -> Path:
        directory = tmp_path.joinpath(dataset.uuid)
        directory.mkdir(exist_ok=True)
        for file_node in dataset.files.all():
            directory.joinpath(file_node.name).write_bytes(b"FASTQ")
        return directory

    monkeypatch.setattr(task, "_dataset_input_path", path_for)
    monkeypatch.setattr(task, "_notify_dataset_error", lambda dataset, error: None)
    return tmp_path


def test_successful_paired_batch_uploads_and_submits() -> None:
    dataset = Dataset("d1", [File("sample_R1.fastq.gz"), File("sample_R2.fastq.gz")])
    batch = Batch("batch-1")
    client = Client(["r1", "r2"])

    report = task.run_batch(Graph(batch, [dataset]), client, batch.uuid, [dataset.uuid], NOW)

    assert report == {"submitted": ["d1"], "failed": [], "requeued": [], "unknown": []}
    assert dataset.status == "RUNNING"
    assert dataset.omics_status == "RUNNING"
    assert dataset.omics_task_id == "remote-task"
    assert dataset.omics_submitted_at == NOW
    assert [file.omics_file_id for file in dataset.files.all()] == ["r1", "r2"]
    assert batch.status == "RUNNING"
    assert batch.uploaded_bytes == 20
    assert client.submits[0][0] == ["r1", "r2"]


def test_paired_fastqs_are_ordered_r1_then_r2() -> None:
    dataset = Dataset("d1", [File("sample_R2.fastq.gz"), File("sample_R1.fastq.gz")])
    batch = Batch("batch-1")
    client = Client(["r1", "r2"])

    report = task.run_batch(
        Graph(batch, [dataset]), client, batch.uuid, [dataset.uuid], NOW
    )

    assert report["submitted"] == ["d1"]
    assert [path.name for path in client.uploaded] == [
        "sample_R1.fastq.gz",
        "sample_R2.fastq.gz",
    ]
    assert client.submits[0][0] == ["r1", "r2"]


def test_r2_without_r1_is_a_dataset_error() -> None:
    dataset = Dataset("d1", [File("sample_R2.fastq.gz")])
    batch = Batch("batch-1")

    report = task.run_batch(Graph(batch, [dataset]), Client(), batch.uuid, [dataset.uuid], NOW)

    assert report["failed"] == ["d1"]
    assert dataset.status == "ERROR"
    assert dataset.omics_status == "ERROR"
    assert "R1 file is missing" in dataset.error_message


def test_invalid_dataset_does_not_stop_the_next_dataset() -> None:
    invalid = Dataset("bad", [File("sample_R2.fastq.gz")])
    valid = Dataset("good", [File("sample_R1.fastq.gz")])
    batch = Batch("batch-1")

    report = task.run_batch(
        Graph(batch, [invalid, valid]),
        Client(["r1"]),
        batch.uuid,
        [invalid.uuid, valid.uuid],
        NOW,
    )

    assert report["failed"] == ["bad"]
    assert report["submitted"] == ["good"]
    assert invalid.status == "ERROR"
    assert valid.omics_task_id == "remote-task"


def test_quota_during_upload_cleans_current_files_and_requeues_remaining() -> None:
    first = Dataset("d1", [File("first_R1.fastq.gz"), File("first_R2.fastq.gz")])
    second = Dataset("d2", [File("next_R1.fastq.gz")])
    batch = Batch("batch-1")
    client = Client(["r1", OmicsQuotaExceeded("full")])

    report = task.run_batch(
        Graph(batch, [first, second]), client, batch.uuid, [first.uuid, second.uuid], NOW
    )

    assert report["requeued"] == ["d1", "d2"]
    assert first.status == second.status == "UPLOAD COMPLETED"
    assert first.omics_status is None and second.omics_status is None
    assert first._relation.status == second._relation.status == "UPLOAD COMPLETED"
    assert client.deleted == ["r1"]
    assert first.files.all()[0].omics_file_id is None
    assert batch.status == "ERROR"


def test_submit_failure_is_held_for_manual_reconciliation_not_retried() -> None:
    dataset = Dataset("d1", [File("sample_R1.fastq.gz")])
    batch = Batch("batch-1")
    client = Client(["r1"], OmicsRequestError("timeout"))
    graph = Graph(batch, [dataset])

    report = task.run_batch(graph, client, batch.uuid, [dataset.uuid], NOW)

    assert report["unknown"] == ["d1"]
    assert dataset.status == "QUEUED"
    assert dataset.omics_status == "SUBMIT_UNKNOWN"
    assert dataset.files.all()[0].omics_file_id == "r1"
    assert client.deleted == []

    task.run_batch(graph, client, batch.uuid, [dataset.uuid], NOW)
    assert len(client.uploaded) == 1
    assert len(client.submits) == 1


def test_known_remote_task_is_never_submitted_twice() -> None:
    dataset = Dataset("d1", [File("sample_R1.fastq.gz")])
    dataset.omics_task_id = "already-submitted"
    batch = Batch("batch-1")
    client = Client()

    report = task.run_batch(Graph(batch, [dataset]), client, batch.uuid, [dataset.uuid], NOW)

    assert report == {"submitted": [], "failed": [], "requeued": [], "unknown": []}
    assert client.uploaded == []
    assert client.submits == []
