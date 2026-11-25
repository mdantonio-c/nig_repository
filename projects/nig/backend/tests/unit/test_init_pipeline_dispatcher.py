"""Unit tests for the local dispatcher security filter (issue #74).

``scripts/init_pipeline.py`` must never queue a ``genome`` dataset on the
local Snakemake pipeline: genome studies are delegated to Omics. These tests
exercise ``select_local_datasets`` against fake ``Dataset``/``Study`` objects,
mirroring the approach already used for ``test_migrate_study_type.py``, so
they run without a live Neo4j connection.
"""

from typing import Optional

from nig.scripts.init_pipeline import LOCAL_STUDY_TYPE, select_local_datasets


class FakeStudy:
    def __init__(self, study_type: Optional[str]) -> None:
        self.study_type = study_type


class FakeParentStudyManager:
    def __init__(self, study: Optional[FakeStudy]) -> None:
        self._study = study

    def single(self) -> Optional[FakeStudy]:
        return self._study


class FakeDataset:
    def __init__(self, uuid: str, study: Optional[FakeStudy]) -> None:
        self.uuid = uuid
        self.parent_study = FakeParentStudyManager(study)


def test_select_local_datasets_keeps_only_exome_studies() -> None:
    exome_dataset = FakeDataset("exome-1", FakeStudy("exome"))
    genome_dataset = FakeDataset("genome-1", FakeStudy("genome"))

    result = select_local_datasets([exome_dataset, genome_dataset])

    assert result == [exome_dataset]


def test_select_local_datasets_skips_genome_dataset_in_upload_completed() -> None:
    # Reproduces the exact security scenario from issue #74: a genome dataset
    # sitting in "UPLOAD COMPLETED" must never be selected for local dispatch.
    genome_dataset = FakeDataset("genome-2", FakeStudy("genome"))

    result = select_local_datasets([genome_dataset])

    assert result == []


def test_select_local_datasets_skips_dataset_without_parent_study() -> None:
    orphan_dataset = FakeDataset("orphan-1", None)

    result = select_local_datasets([orphan_dataset])

    assert result == []


def test_select_local_datasets_skips_dataset_with_missing_study_type() -> None:
    # A study without a study_type (e.g. not yet migrated) must not be
    # treated as local: fail closed, not open.
    untyped_dataset = FakeDataset("untyped-1", FakeStudy(None))

    result = select_local_datasets([untyped_dataset])

    assert result == []


def test_select_local_datasets_returns_empty_list_for_empty_input() -> None:
    assert select_local_datasets([]) == []


def test_local_study_type_constant_is_exome() -> None:
    assert LOCAL_STUDY_TYPE == "exome"
