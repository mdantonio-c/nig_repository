"""Tests for Omics batch execution with an entirely mocked remote client."""

import inspect
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


class Members(Manager):
    """Both ends of the SENT_TO_OMICS relationship."""

    def __init__(self, values: List[Any], relation_for: Any) -> None:
        super().__init__(values)
        self.relation_for = relation_for

    def relationship(self, node: Any) -> Any:
        return self.relation_for(node)


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
        self._batches: List[Any] = []
        self.omics_output_prefix: Optional[str] = None
        self.saves = 0

    def save(self) -> None:
        self.saves += 1

    @property
    def omics_batch(self) -> Any:
        return Members(self._batches, lambda _: self._relation)


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
        self.members: List[Any] = []
        self.saves = 0

    def save(self) -> None:
        self.saves += 1

    @property
    def datasets(self) -> Members:
        return Members(self.members, lambda dataset: dataset._relation)


class Graph:
    def __init__(self, batch: Batch, datasets: List[Dataset]) -> None:
        self.OmicsBatch = Model({batch.uuid: batch})
        self.Dataset = Model({dataset.uuid: dataset for dataset in datasets})
        batch.members = list(datasets)
        for dataset in datasets:
            dataset._batches = [batch]


class Client:
    def __init__(self, uploads: Optional[List[Any]] = None, submit: Optional[Any] = None) -> None:
        self.uploads = list(uploads or [])
        self.submit = submit if submit is not None else {"task_id": "remote-task"}
        self.uploaded: List[Path] = []
        self.remote_names: List[Optional[str]] = []
        self.deleted: List[str] = []
        self.submits: List[Any] = []

    def upload_file(
        self, path: Path, tags: List[str], remote_filename: Optional[str] = None
    ) -> str:
        self.uploaded.append(path)
        self.remote_names.append(remote_filename)
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

    assert report == {
        "submitted": ["d1"],
        "failed": [],
        "requeued": [],
        "unknown": [],
        "missing": [],
    }
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
    # nothing failed: every claim was returned to the dispatcher
    assert batch.status == "PARTIAL"


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

    assert report == {
        "submitted": [],
        "failed": [],
        "requeued": [],
        "unknown": [],
        "missing": [],
    }
    assert client.uploaded == []
    assert client.submits == []


def test_remote_names_are_unique_per_dataset() -> None:
    # Omics resumes uploads by filename: the same local name in two datasets
    # must never collide remotely.
    first = Dataset("d1", [File("sample_R1.fastq.gz")])
    second = Dataset("d2", [File("sample_R1.fastq.gz")])
    batch = Batch("batch-1")
    client = Client(["r1", "r2"])

    task.run_batch(
        Graph(batch, [first, second]), client, batch.uuid, ["d1", "d2"], NOW
    )

    assert client.remote_names == ["d1_sample_R1.fastq.gz", "d2_sample_R1.fastq.gz"]


def test_output_prefix_is_persisted_before_submit() -> None:
    dataset = Dataset("d1", [File("sample_R1.fastq.gz")])
    batch = Batch("batch-1")
    client = Client(["r1"])
    seen: List[Any] = []
    original = client.submit_nig_germline

    def submit(input_ids: List[str], **kwargs: Any) -> Dict[str, str]:
        seen.append((dataset.omics_status, dataset.omics_output_prefix))
        return original(input_ids, **kwargs)

    client.submit_nig_germline = submit  # type: ignore[assignment]
    task.run_batch(Graph(batch, [dataset]), client, batch.uuid, ["d1"], NOW)

    assert seen == [("SUBMITTING", "sample_d1.g.vcf.gz")]
    assert client.submits[0][1]["output_vcf"] == "sample_d1.g.vcf.gz"


def test_redelivery_reuses_uploaded_files_without_duplicates() -> None:
    dataset = Dataset("d1", [File("sample_R1.fastq.gz"), File("sample_R2.fastq.gz")])
    r1 = dataset.files.all()[0]
    r1.omics_file_id, r1.omics_status = "already-r1", "UPLOADED"
    batch = Batch("batch-1")
    batch.uploaded_bytes = 10
    client = Client(["r2"])

    report = task.run_batch(Graph(batch, [dataset]), client, batch.uuid, ["d1"], NOW)

    assert report["submitted"] == ["d1"]
    assert [path.name for path in client.uploaded] == ["sample_R2.fastq.gz"]
    assert client.submits[0][0] == ["already-r1", "r2"]
    # only the new upload is accounted, the previous one was already counted
    assert batch.uploaded_bytes == 20


def test_redelivery_after_submitting_fails_closed() -> None:
    dataset = Dataset("d1", [File("sample_R1.fastq.gz")])
    dataset.omics_status = "SUBMITTING"
    batch = Batch("batch-1")
    client = Client()

    report = task.run_batch(Graph(batch, [dataset]), client, batch.uuid, ["d1"], NOW)

    assert report["unknown"] == ["d1"]
    assert dataset.omics_status == "SUBMIT_UNKNOWN"
    assert dataset._relation.status == "SUBMIT_UNKNOWN"
    assert client.uploaded == [] and client.submits == []
    # remote task may exist: the batch keeps holding its quota
    assert batch.status == "RUNNING"


def test_unexpected_error_shows_generic_message_only() -> None:
    dataset = Dataset("d1", [File("sample_R1.fastq.gz"), File("sample_R2.fastq.gz")])
    batch = Batch("batch-1")
    secret_detail = OmicsRequestError("HTTP 500 at /data/input/g/s/d1 token=abc")
    client = Client(["r1", secret_detail])

    report = task.run_batch(Graph(batch, [dataset]), client, batch.uuid, ["d1"], NOW)

    assert report["failed"] == ["d1"]
    assert dataset.error_message == task.USER_ANALYSIS_ERROR
    assert "/data/input" not in dataset.error_message
    assert "HTTP 500" in dataset.omics_error_message
    assert client.deleted == ["r1"]
    assert batch.status == "ERROR"


def test_non_omics_exception_is_contained_per_dataset() -> None:
    broken = Dataset("bad", [File("sample_R1.fastq.gz")])
    valid = Dataset("good", [File("other_R1.fastq.gz")])
    batch = Batch("batch-1")
    client = Client([RuntimeError("disk read failed"), "r1"])

    report = task.run_batch(
        Graph(batch, [broken, valid]), client, batch.uuid, ["bad", "good"], NOW
    )

    assert report["failed"] == ["bad"]
    assert report["submitted"] == ["good"]
    assert broken.error_message == task.USER_ANALYSIS_ERROR
    assert broken.omics_error_message == "Unexpected error: disk read failed"


class FlakyDataset(Dataset):
    """A dataset whose graph writes fail once Omics has accepted the task."""

    def __init__(self, uuid: str, files: List[Any], fail_always: bool = False) -> None:
        super().__init__(uuid, files)
        self.fail_always = fail_always
        self.failures = 0

    def save(self) -> None:
        if self.omics_status == "RUNNING" or (
            self.fail_always and self.omics_status == "SUBMIT_UNKNOWN"
        ):
            self.failures += 1
            raise RuntimeError("graph unavailable")
        super().save()


def test_save_failure_after_accepted_submit_holds_instead_of_cleaning() -> None:
    dataset = FlakyDataset("d1", [File("sample_R1.fastq.gz")])
    batch = Batch("batch-1")
    client = Client(["r1"])

    report = task.run_batch(Graph(batch, [dataset]), client, batch.uuid, ["d1"], NOW)

    assert report["unknown"] == ["d1"] and report["failed"] == []
    assert dataset.omics_status == "SUBMIT_UNKNOWN"
    assert dataset.status == "QUEUED"
    assert dataset.omics_task_id == "remote-task"
    assert "Omics accepted the task" in dataset.omics_error_message
    assert dataset._relation.status == "SUBMIT_UNKNOWN"
    assert dataset.files.all()[0].omics_file_id == "r1"
    assert client.deleted == []
    # the remote task exists: the batch keeps holding its quota
    assert batch.status == "RUNNING"


def test_relation_failure_after_accepted_submit_holds_instead_of_cleaning() -> None:
    class FlakyRelation(Relation):
        def save(self) -> None:
            if self.status == "RUNNING":
                raise RuntimeError("graph unavailable")
            super().save()

    dataset = Dataset("d1", [File("sample_R1.fastq.gz")])
    dataset._relation = FlakyRelation()
    batch = Batch("batch-1")
    client = Client(["r1"])

    report = task.run_batch(Graph(batch, [dataset]), client, batch.uuid, ["d1"], NOW)

    assert report["unknown"] == ["d1"] and report["submitted"] == []
    assert dataset.omics_status == "SUBMIT_UNKNOWN"
    assert dataset.omics_task_id == "remote-task"
    assert dataset._relation.status == "SUBMIT_UNKNOWN"
    assert client.deleted == []
    assert batch.status == "RUNNING"


def test_failed_hold_does_not_stop_the_next_dataset() -> None:
    broken = FlakyDataset("bad", [File("sample_R1.fastq.gz")], fail_always=True)
    valid = Dataset("good", [File("other_R1.fastq.gz")])
    batch = Batch("batch-1")
    client = Client(["r1", "r2"])

    report = task.run_batch(
        Graph(batch, [broken, valid]), client, batch.uuid, ["bad", "good"], NOW
    )

    assert broken.failures == 2
    assert report["submitted"] == ["good"]
    assert report["failed"] == []
    assert client.deleted == []
    assert len(client.submits) == 2


def test_failure_before_submit_is_still_a_cleaned_dataset_error() -> None:
    class PreSubmitFailure(Dataset):
        def save(self) -> None:
            if self.omics_status == "SUBMITTING":
                raise RuntimeError("graph unavailable")
            super().save()

    dataset = PreSubmitFailure("d1", [File("sample_R1.fastq.gz")])
    batch = Batch("batch-1")
    client = Client(["r1"])

    report = task.run_batch(Graph(batch, [dataset]), client, batch.uuid, ["d1"], NOW)

    assert report["failed"] == ["d1"] and report["unknown"] == []
    assert client.submits == []
    assert client.deleted == ["r1"]
    assert dataset.omics_status == "ERROR"


def test_unrecordable_error_does_not_stop_the_next_dataset() -> None:
    class Unwritable(Dataset):
        def save(self) -> None:
            if self.omics_status in ("SUBMITTING", "ERROR"):
                raise RuntimeError("graph unavailable")
            super().save()

    broken = Unwritable("bad", [File("sample_R1.fastq.gz")])
    valid = Dataset("good", [File("other_R1.fastq.gz")])
    batch = Batch("batch-1")
    client = Client(["r1", "r2"])

    report = task.run_batch(
        Graph(batch, [broken, valid]), client, batch.uuid, ["bad", "good"], NOW
    )

    assert report["submitted"] == ["good"]
    assert len(client.submits) == 1
    assert batch.status == "RUNNING"


def test_deleted_dataset_is_reported_and_does_not_block_the_batch() -> None:
    batch = Batch("batch-1")

    report = task.run_batch(Graph(batch, []), Client(), batch.uuid, ["gone"], NOW)

    assert report["missing"] == ["gone"]
    # no member left: the batch is closed, freeing its quota slot
    assert batch.status == "ERROR"


def test_batch_is_closed_when_every_dataset_fails() -> None:
    dataset = Dataset("d1", [File("sample_R2.fastq.gz")])
    batch = Batch("batch-1")

    task.run_batch(Graph(batch, [dataset]), Client(), batch.uuid, ["d1"], NOW)

    assert dataset._relation.status == "ERROR"
    assert batch.status == "ERROR"


def test_task_does_nothing_when_omics_is_disabled(monkeypatch: Any) -> None:
    calls: List[str] = []
    monkeypatch.setattr(task, "omics_enabled", lambda: False)
    monkeypatch.setattr(task, "run_batch", lambda *a, **k: calls.append("run"))
    monkeypatch.setattr(task, "client_from_env", lambda: calls.append("client"))

    inspect.unwrap(task.omics_run_batch.__wrapped__)(None, "batch-1", ["d1"])

    assert calls == []
