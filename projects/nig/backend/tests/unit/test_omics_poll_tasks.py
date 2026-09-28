"""Tests for Omics status polling and result retrieval with fake clients."""

import inspect
from datetime import datetime, timedelta
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


class Links(Manager):
    def __init__(self, values: List[Any], relation_for: Any) -> None:
        super().__init__(values)
        self.relation_for = relation_for

    def relationship(self, node: Any) -> Any:
        return self.relation_for(node)


class Batch:
    def __init__(self) -> None:
        self.status = "RUNNING"
        self.members: List[Any] = []
        self.saves = 0

    @property
    def datasets(self) -> Links:
        return Links(self.members, lambda dataset: dataset._relation)

    def save(self) -> None:
        self.saves += 1


class Dataset:
    def __init__(
        self, uuid: str, remote_task: str = "task-1", batch: Optional[Batch] = None
    ) -> None:
        self.uuid = uuid
        self.name = uuid
        self.omics_task_id = remote_task
        self.omics_status = "RUNNING"
        self.status = "RUNNING"
        self.omics_error_message: Optional[str] = None
        self.error_message: Optional[str] = None
        self.omics_status_update: Optional[datetime] = None
        self.status_update: Optional[datetime] = None
        self.omics_fetch_attempts: Optional[int] = None
        self.parent_study = Manager([type("Study", (), {"uuid": "s", "name": "S"})()])
        self._batch = batch or Batch()
        self._batch.members.append(self)
        self._relation = Relation()
        self._artifacts: List[Any] = []
        self.saves = 0

    @property
    def omics_batch(self) -> Links:
        return Links([self._batch], lambda _: self._relation)

    @property
    def omics_artifacts(self) -> Manager:
        return Manager(self._artifacts)

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
        self.kind: Optional[str] = None
        self.status: Optional[str] = None
        self.local_path: Optional[str] = None
        self.size = 0
        self.dataset = type(
            "DatasetLink",
            (),
            {"connect": lambda _, dataset: dataset._artifacts.append(self)},
        )()

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
    assert complete._relation.status == "FETCHING"
    assert complete.omics_fetch_attempts == 1
    assert calls == ["complete"]


def test_poll_remote_error_marks_dataset_error() -> None:
    dataset = Dataset("failed")

    report = poll.poll_tasks(
        Graph([dataset]), PollClient({"task-1": "Error"}), now=NOW
    )

    assert report["failed"] == ["failed"]
    assert dataset.status == dataset.omics_status == "ERROR"
    assert dataset.error_message == poll.USER_ANALYSIS_ERROR
    assert "Remote task reported Error" in dataset.omics_error_message
    assert dataset._relation.status == "ERROR"
    assert dataset._batch.status == "ERROR"


def test_dispatch_failure_keeps_fetching_for_recovery() -> None:
    dataset = Dataset("complete")

    def broken(uuid: str) -> str:
        raise RuntimeError("broker down")

    report = poll.poll_tasks(
        Graph([dataset]), PollClient({"task-1": "Complete"}), send_task=broken, now=NOW
    )

    # FETCHING is persisted before enqueuing: the recovery loop owns it now
    assert report["fetching"] == []
    assert dataset.omics_status == "FETCHING"
    assert dataset.omics_status_update == NOW

    calls: List[str] = []
    poll.poll_tasks(
        Graph([dataset]),
        PollClient({}),
        send_task=lambda uuid: calls.append(uuid) or "id",
        now=NOW + timedelta(minutes=10),
        retry_minutes=60,
    )
    assert calls == []  # still within the back-off

    report = poll.poll_tasks(
        Graph([dataset]),
        PollClient({}),
        send_task=lambda uuid: calls.append(uuid) or "id",
        now=NOW + timedelta(minutes=61),
        retry_minutes=60,
    )
    assert calls == ["complete"]
    assert report["fetching"] == ["complete"]
    assert dataset.omics_fetch_attempts == 2


def test_fetching_is_abandoned_after_max_attempts() -> None:
    dataset = Dataset("stuck")
    dataset.omics_status = "FETCHING"
    dataset.omics_fetch_attempts = 3
    dataset.omics_error_message = "Omics result retrieval failed: HTTP 502"
    calls: List[str] = []

    report = poll.poll_tasks(
        Graph([dataset]),
        PollClient({}),
        send_task=lambda uuid: calls.append(uuid) or "id",
        now=NOW,
        max_attempts=3,
    )

    assert report["failed"] == ["stuck"]
    assert calls == []
    assert dataset.status == "ERROR"
    assert dataset.error_message == poll.USER_ANALYSIS_ERROR
    assert "abandoned after 3 attempts" in dataset.omics_error_message
    assert "HTTP 502" in dataset.omics_error_message
    assert dataset._batch.status == "ERROR"


def test_cleanup_pending_recheck_consumes_no_attempts() -> None:
    dataset = Dataset("pending")
    dataset.omics_status = "CLEANUP PENDING"
    dataset.omics_fetch_attempts = 5
    calls: List[str] = []

    report = poll.poll_tasks(
        Graph([dataset]),
        PollClient({}),
        send_task=lambda uuid: calls.append(uuid) or "id",
        now=NOW,
        max_attempts=5,
    )

    assert report["fetching"] == ["pending"]
    assert calls == ["pending"]
    assert dataset.omics_status == "CLEANUP PENDING"
    assert dataset.omics_fetch_attempts == 5


def test_poll_error_on_one_dataset_does_not_stop_the_others() -> None:
    broken, healthy = Dataset("broken", "task-x"), Dataset("healthy", "task-1")

    report = poll.poll_tasks(
        Graph([broken, healthy]), PollClient({"task-1": "Processing"}), now=NOW
    )

    assert report["poll_errors"] == ["broken"]
    assert report["running"] == ["healthy"]
    assert broken.omics_status == "RUNNING"


def test_poll_does_nothing_when_omics_is_disabled(monkeypatch: Any) -> None:
    calls: List[str] = []
    monkeypatch.setattr(poll, "omics_enabled", lambda: False)
    monkeypatch.setattr(poll, "poll_tasks", lambda *a, **k: calls.append("poll"))
    monkeypatch.setattr(poll, "client_from_env", lambda: calls.append("client"))

    inspect.unwrap(poll.omics_poll_tasks.__wrapped__)(None)

    assert calls == []


def test_fetch_does_nothing_when_omics_is_disabled(monkeypatch: Any) -> None:
    calls: List[str] = []
    monkeypatch.setattr(fetch, "omics_enabled", lambda: False)
    monkeypatch.setattr(fetch, "fetch_results", lambda *a, **k: calls.append("fetch"))
    monkeypatch.setattr(fetch, "client_from_env", lambda: calls.append("client"))

    inspect.unwrap(fetch.omics_fetch_results.__wrapped__)(None, "d1")

    assert calls == []


def test_fetch_skips_non_fetching_dataset() -> None:
    dataset = Dataset("d1")
    graph = Graph([dataset])

    assert fetch.fetch_results(graph, object(), "d1", NOW) == {
        "downloaded": [],
        "skipped": True,
    }


class FetchClient:
    def __init__(self, remains_remote: bool = False, fail_on: str = "") -> None:
        self.remains_remote = remains_remote
        self.fail_on = fail_on
        self.downloads: List[str] = []
        self.served: set = set()

    def get_task_files(self, task_id: str) -> List[Dict[str, Any]]:
        # Omics removes an output after its first complete download. The
        # server exposes the graph class name in ``_kind`` (``Vcf``/``Bam``,
        # shared by an artifact and its index) and distinguishes an index
        # only through the ``extension`` suffix.
        return [
            output
            for output in (
                {"_kind": "Vcf", "file_id": "g", "user_filename": "a.g.vcf.gz", "size": 3, "extension": "vcf.gz"},
                {"_kind": "Vcf", "file_id": "t", "user_filename": "a.g.vcf.gz.tbi", "size": 3, "extension": "vcf.gz.tbi"},
                {"_kind": "Bam", "file_id": "b", "user_filename": "a.bam", "size": 3, "extension": "bam"},
                {"_kind": "Bam", "file_id": "i", "user_filename": "a.bam.bai", "size": 3, "extension": "bam.bai"},
            )
            if output["file_id"] not in self.served
        ]

    @staticmethod
    def ensure_free_space(directory: Path, required_bytes: int) -> None:
        pass

    def download_file(self, file_id: str, destination: Path, expected_size: int) -> Path:
        self.downloads.append(file_id)
        if file_id == self.fail_on:
            raise fetch.OmicsError("HTTP 502")
        destination.write_bytes(b"abc")
        self.served.add(file_id)
        return destination

    def list_uploaded_files(self) -> List[Dict[str, str]]:
        return [{"file_id": "g", "user_filename": "a.g.vcf.gz"}] if self.remains_remote else []


def test_fetch_persists_downloaded_outputs_and_completes_dataset(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dataset = Dataset("d1")
    dataset.omics_status = "FETCHING"
    graph = Graph([dataset])
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)

    report = fetch.fetch_results(graph, FetchClient(), "d1", NOW)

    assert report == {"downloaded": ["g", "t", "b", "i"], "cleanup_pending": False}
    assert dataset.status == dataset.omics_status == "COMPLETED"
    assert {artifact.kind for artifact in graph._artifacts.values()} == {"GVCF", "TBI", "BAM", "BAI"}
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


def test_fetch_rejects_a_traversal_output_filename(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dataset = Dataset("d1")
    dataset.omics_status = "FETCHING"
    graph = Graph([dataset])
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)

    class TraversalClient(FetchClient):
        def get_task_files(self, task_id: str) -> List[Dict[str, Any]]:
            outputs = super().get_task_files(task_id)
            outputs[0]["user_filename"] = "../outside.g.vcf.gz"
            return outputs

    report = fetch.fetch_results(graph, TraversalClient(), "d1", NOW)

    assert report["downloaded"] == []
    assert dataset.status == "RUNNING"
    assert dataset.omics_status == "FETCHING"
    assert "Unexpected Omics GVCF output filename" in dataset.omics_error_message


def test_fetch_rejects_non_matching_tabix_index(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dataset = Dataset("d1")
    dataset.omics_status = "FETCHING"
    graph = Graph([dataset])
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)

    class MismatchedIndexClient(FetchClient):
        def get_task_files(self, task_id: str) -> List[Dict[str, Any]]:
            outputs = super().get_task_files(task_id)
            outputs[1]["user_filename"] = "other.g.vcf.gz.tbi"
            return outputs

    report = fetch.fetch_results(graph, MismatchedIndexClient(), "d1", NOW)

    assert report["downloaded"] == []
    assert dataset.status == "RUNNING"
    assert dataset.omics_status == "FETCHING"
    assert "TBI output does not match" in dataset.omics_error_message


def test_fetch_rejects_duplicate_retained_output_kind(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dataset = Dataset("d1")
    dataset.omics_status = "FETCHING"
    graph = Graph([dataset])
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)

    class DuplicateGvcfClient(FetchClient):
        def get_task_files(self, task_id: str) -> List[Dict[str, Any]]:
            outputs = super().get_task_files(task_id)
            outputs.append(
                {
                    "_kind": "Vcf",
                    "file_id": "g2",
                    "user_filename": "b.g.vcf.gz",
                    "size": 3,
                    "extension": "vcf.gz",
                }
            )
            return outputs

    report = fetch.fetch_results(graph, DuplicateGvcfClient(), "d1", NOW)

    assert report["downloaded"] == []
    assert dataset.status == "RUNNING"
    assert dataset.omics_status == "FETCHING"
    assert "must include exactly" in dataset.omics_error_message


def _fetching(uuid: str = "d1", batch: Optional[Batch] = None) -> Dataset:
    dataset = Dataset(uuid, batch=batch)
    dataset.omics_status = "FETCHING"
    dataset._relation.status = "FETCHING"
    return dataset


def test_fetch_completion_closes_the_batch(monkeypatch: Any, tmp_path: Path) -> None:
    dataset = _fetching()
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)

    fetch.fetch_results(Graph([dataset]), FetchClient(), "d1", NOW)

    assert dataset._relation.status == "COMPLETED"
    assert dataset._batch.status == "COMPLETED"


def test_batch_stays_active_until_every_dataset_is_closed(
    monkeypatch: Any, tmp_path: Path
) -> None:
    batch = Batch()
    first, second = _fetching("d1", batch), Dataset("d2", batch=batch)
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)

    fetch.fetch_results(Graph([first, second]), FetchClient(), "d1", NOW)
    assert batch.status == "RUNNING"

    poll.poll_tasks(Graph([second]), PollClient({"task-1": "Error"}), now=NOW)
    # one COMPLETED and one ERROR: the batch did not fully succeed
    assert batch.status == "ERROR"


def test_fetch_resumes_without_requesting_downloaded_outputs(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dataset = _fetching()
    graph = Graph([dataset])
    client = FetchClient(fail_on="t")
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)

    report = fetch.fetch_results(graph, client, "d1", NOW)

    assert "HTTP 502" in report["error"]
    assert dataset.omics_status == "FETCHING"
    assert dataset.status == "RUNNING"
    assert graph._artifacts["t"].status == "ERROR"
    assert graph._artifacts["g"].status == "DOWNLOADED"

    client.fail_on = ""
    report = fetch.fetch_results(graph, client, "d1", NOW)

    # gVCF was deleted remotely after the first download: never requested again
    assert client.downloads == ["g", "t", "t", "b", "i"]
    assert report == {"downloaded": ["t", "b", "i"], "cleanup_pending": False}
    assert dataset.status == "COMPLETED"


def test_fetch_error_keeps_technical_detail_out_of_user_message(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dataset = _fetching()
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)

    fetch.fetch_results(Graph([dataset]), FetchClient(fail_on="g"), "d1", NOW)

    assert dataset.error_message is None
    assert "HTTP 502" in dataset.omics_error_message
    assert dataset.omics_status_update == NOW


def test_cleanup_pending_recheck_completes_without_downloading(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dataset = _fetching()
    graph = Graph([dataset])
    client = FetchClient(remains_remote=True)
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)
    fetch.fetch_results(graph, client, "d1", NOW)
    assert dataset.omics_status == "CLEANUP PENDING"
    assert dataset._batch.status == "RUNNING"

    client.remains_remote = False
    later = NOW + timedelta(hours=2)
    report = fetch.fetch_results(graph, client, "d1", later)

    assert report == {"downloaded": [], "cleanup_pending": False}
    assert client.downloads == ["g", "t", "b", "i"]
    assert dataset.status == dataset.omics_status == "COMPLETED"
    assert dataset.status_update == later
    assert dataset._batch.status == "COMPLETED"


def test_cleanup_pending_with_lost_local_output_downloads_it_again(
    monkeypatch: Any, tmp_path: Path
) -> None:
    dataset = _fetching()
    graph = Graph([dataset])
    client = FetchClient(remains_remote=True)
    monkeypatch.setattr(fetch, "_output_dir", lambda dataset: tmp_path)
    fetch.fetch_results(graph, client, "d1", NOW)
    tmp_path.joinpath("a.bam").chmod(0o640)
    tmp_path.joinpath("a.bam").unlink()
    client.served.discard("b")  # still listed remotely
    client.remains_remote = False

    report = fetch.fetch_results(graph, client, "d1", NOW)

    assert report["downloaded"] == ["b"]
    assert dataset.status == "COMPLETED"
