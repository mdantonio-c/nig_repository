"""Unit tests for :mod:`nig.scripts.check_omics_state` (issue #75).

Mirrors the fake-graph approach used for ``test_migrate_study_type.py``: no
live Neo4j connection is needed, only fake objects exposing the same small
surface used by the script (``.nodes.filter/.all``, relationship managers
with ``.all()``/``.single()``).
"""

from typing import Any, List, Optional

from nig.scripts.check_omics_state import (
    REPORT_TYPE,
    build_report,
    find_artifacts_without_dataset,
    find_datasets_with_task_but_no_uploaded_file,
    find_downloaded_artifacts_without_local_path,
    find_inconsistencies,
)


class FakeFile:
    def __init__(self, omics_file_id: Optional[str]) -> None:
        self.omics_file_id = omics_file_id


class FakeFilesManager:
    def __init__(self, files: List[FakeFile]) -> None:
        self._files = files

    def all(self) -> List[FakeFile]:
        return self._files


class FakeDataset:
    def __init__(
        self,
        uuid: str,
        omics_task_id: Optional[str] = None,
        files: Optional[List[FakeFile]] = None,
    ) -> None:
        self.uuid = uuid
        self.omics_task_id = omics_task_id
        self.files = FakeFilesManager(files or [])


class FakeDatasetNodeSet:
    def __init__(self, datasets: List[FakeDataset]) -> None:
        self._datasets = datasets

    def filter(self, **kwargs: Any) -> "FakeDatasetNodeSet":
        assert kwargs == {"omics_task_id__isnull": False}
        return FakeDatasetNodeSet(
            [d for d in self._datasets if d.omics_task_id is not None]
        )

    def all(self) -> List[FakeDataset]:
        return self._datasets


class FakeDatasetManager:
    def __init__(self, datasets: List[FakeDataset]) -> None:
        self.nodes = FakeDatasetNodeSet(datasets)


class FakeDatasetRelManager:
    def __init__(self, dataset: Optional[FakeDataset]) -> None:
        self._dataset = dataset

    def single(self) -> Optional[FakeDataset]:
        return self._dataset


class FakeArtifact:
    def __init__(
        self,
        uuid: str,
        dataset: Optional[FakeDataset] = None,
        status: Optional[str] = None,
        local_path: Optional[str] = None,
    ) -> None:
        self.uuid = uuid
        self.dataset = FakeDatasetRelManager(dataset)
        self.status = status
        self.local_path = local_path


class FakeArtifactNodeSet:
    def __init__(self, artifacts: List[FakeArtifact]) -> None:
        self._artifacts = artifacts

    def all(self) -> List[FakeArtifact]:
        return self._artifacts


class FakeArtifactManager:
    def __init__(self, artifacts: List[FakeArtifact]) -> None:
        self.nodes = FakeArtifactNodeSet(artifacts)


class FakeGraph:
    def __init__(
        self,
        datasets: Optional[List[FakeDataset]] = None,
        artifacts: Optional[List[FakeArtifact]] = None,
    ) -> None:
        self.Dataset = FakeDatasetManager(datasets or [])
        self.OmicsArtifact = FakeArtifactManager(artifacts or [])


def test_find_datasets_with_task_but_no_uploaded_file() -> None:
    good = FakeDataset("d-good", omics_task_id="t1", files=[FakeFile("f1")])
    bad = FakeDataset("d-bad", omics_task_id="t2", files=[FakeFile(None)])
    untouched = FakeDataset("d-untouched", omics_task_id=None)
    graph = FakeGraph(datasets=[good, bad, untouched])

    result = find_datasets_with_task_but_no_uploaded_file(graph)

    assert result == ["d-bad"]


def test_find_artifacts_without_dataset() -> None:
    ds = FakeDataset("d-1")
    linked = FakeArtifact("a-linked", dataset=ds)
    orphan = FakeArtifact("a-orphan", dataset=None)
    graph = FakeGraph(artifacts=[linked, orphan])

    result = find_artifacts_without_dataset(graph)

    assert result == ["a-orphan"]


def test_find_downloaded_artifacts_without_local_path() -> None:
    ok = FakeArtifact("a-ok", status="DOWNLOADED", local_path="/data/output/x")
    bad = FakeArtifact("a-bad", status="DOWNLOADED", local_path=None)
    pending = FakeArtifact("a-pending", status="DISCOVERED", local_path=None)
    graph = FakeGraph(artifacts=[ok, bad, pending])

    result = find_downloaded_artifacts_without_local_path(graph)

    assert result == ["a-bad"]


def test_find_inconsistencies_aggregates_all_checks() -> None:
    dataset = FakeDataset("d-bad", omics_task_id="t2", files=[FakeFile(None)])
    orphan_artifact = FakeArtifact("a-orphan", dataset=None)
    bad_artifact = FakeArtifact(
        "a-bad", dataset=dataset, status="DOWNLOADED", local_path=None
    )
    graph = FakeGraph(datasets=[dataset], artifacts=[orphan_artifact, bad_artifact])

    issues = find_inconsistencies(graph)

    assert issues["dataset_with_task_no_uploaded_file"] == ["d-bad"]
    assert issues["artifact_without_dataset"] == ["a-orphan"]
    assert issues["artifact_downloaded_without_local_path"] == ["a-bad"]


def test_build_report_is_read_only_and_counts_total_issues() -> None:
    dataset = FakeDataset("d-bad", omics_task_id="t2", files=[FakeFile(None)])
    graph = FakeGraph(datasets=[dataset])

    report = build_report(graph)

    assert report["report_type"] == REPORT_TYPE
    assert report["read_only"] is True
    assert report["total_issues"] == 1
    assert report["issues"]["dataset_with_task_no_uploaded_file"] == ["d-bad"]


def test_build_report_no_issues_on_clean_graph() -> None:
    graph = FakeGraph()

    report = build_report(graph)

    assert report["total_issues"] == 0
