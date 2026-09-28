"""Safe preparation of study-type-separated joint analyses.

The current ``Joint_samples.smk`` has shared global outputs and is not safe for
``genome`` data. This module prepares deterministic, homogeneous manifests but
deliberately does not authorise genome execution until the standard workflow is
versioned and validated.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

SUPPORTED_STUDY_TYPES = {"exome", "genome"}


class JointAnalysisSelectionError(ValueError):
    """The selected datasets cannot safely form a joint-analysis cohort."""


@dataclass(frozen=True)
class JointDataset:
    uuid: str
    sample: str
    output_path: Path
    study_type: str


def select_joint_datasets(datasets: Iterable[Any]) -> Dict[str, List[Any]]:
    """Partition completed datasets by study type, failing closed if untyped."""
    cohorts: Dict[str, List[Any]] = {"exome": [], "genome": []}
    for dataset in datasets:
        study = dataset.parent_study.single()
        study_type = study.study_type if study is not None else None
        if study_type not in SUPPORTED_STUDY_TYPES:
            raise JointAnalysisSelectionError(
                f"Dataset {dataset.uuid} has no supported study type"
            )
        cohorts[study_type].append(dataset)
    return cohorts


def require_homogeneous(datasets: Iterable[Any], study_type: str) -> List[Any]:
    """Return a non-empty, single-study-type cohort or raise an explicit error."""
    selected = list(datasets)
    if study_type not in SUPPORTED_STUDY_TYPES:
        raise JointAnalysisSelectionError(f"Unsupported study type: {study_type}")
    if not selected:
        raise JointAnalysisSelectionError("Joint analysis requires at least one dataset")
    actual = select_joint_datasets(selected)
    mixed = [kind for kind, members in actual.items() if members]
    if mixed != [study_type]:
        raise JointAnalysisSelectionError(
            f"Joint analysis cohort must contain only {study_type} datasets"
        )
    return selected


def joint_workdir(root: Path, task_id: str, study_type: str) -> Path:
    """Return a type-namespaced work directory for a future joint task."""
    if study_type not in SUPPORTED_STUDY_TYPES:
        raise JointAnalysisSelectionError(f"Unsupported study type: {study_type}")
    return root.joinpath("jobs", "joint", study_type, task_id)
