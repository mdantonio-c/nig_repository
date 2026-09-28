"""Safety tests for study-type-separated joint-analysis preparation."""

from typing import Any, Optional

import pytest
from nig.services.joint_analysis import (
    JointAnalysisSelectionError,
    joint_workdir,
    require_homogeneous,
    select_joint_datasets,
)


class Manager:
    def __init__(self, value: Any) -> None:
        self.value = value

    def single(self) -> Any:
        return self.value


class Dataset:
    def __init__(self, uuid: str, study_type: Optional[str]) -> None:
        self.uuid = uuid
        self.parent_study = Manager(
            type("Study", (), {"study_type": study_type})() if study_type else None
        )


def test_select_joint_datasets_partitions_exome_and_genome() -> None:
    exome = Dataset("e", "exome")
    genome = Dataset("g", "genome")

    cohorts = select_joint_datasets([exome, genome])

    assert cohorts == {"exome": [exome], "genome": [genome]}


def test_untyped_dataset_is_rejected_fail_closed() -> None:
    with pytest.raises(JointAnalysisSelectionError):
        select_joint_datasets([Dataset("unknown", None)])


def test_homogeneous_cohort_accepts_the_requested_type() -> None:
    datasets = [Dataset("e1", "exome"), Dataset("e2", "exome")]

    assert require_homogeneous(datasets, "exome") == datasets


@pytest.mark.parametrize("study_type", ["exome", "genome"])
def test_mixed_cohort_is_rejected(study_type: str) -> None:
    with pytest.raises(JointAnalysisSelectionError):
        require_homogeneous([Dataset("e", "exome"), Dataset("g", "genome")], study_type)


def test_workdirs_are_namespaced_by_study_type(tmp_path: Any) -> None:
    exome = joint_workdir(tmp_path, "task", "exome")
    genome = joint_workdir(tmp_path, "task", "genome")

    assert exome != genome
    assert exome.parts[-2] == "exome"
    assert genome.parts[-2] == "genome"
