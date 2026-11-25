"""Safe preparation of study-type-separated joint analyses.

Exome and genome cohorts are never aggregated together: each study type has
its own manifest, GenomicsDB workspace, outputs and reference bundle, all read
from ``snakemake/joint.yaml``. The genome branch stays disabled until
``JOINT_GENOME_ENABLE`` is explicitly set, after validation on real Omics gVCFs.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml
from pandas import DataFrame
from restapi.env import Env

SUPPORTED_STUDY_TYPES = {"exome", "genome"}
JOINT_CONFIG_FILE = "joint.yaml"
JOINT_MANIFEST_FILE = "joint.csv"
JOINT_RUN_CONFIG_FILE = "joint_run.yaml"
REQUIRED_SETTINGS = {
    "reference_id",
    "fasta",
    "intervals",
    "workspace",
    "genotype_dir",
    "filtered_dir",
    "java_heap",
    "reader_threads",
    "batch_size",
    "annotations",
    "allow_unmarked_workspace",
}
# same FASTQ naming handled by the local exome pipeline
EXOME_FASTQ_PATTERN = r"([a-zA-Z0-9_-]+)_(R[12]).fastq.gz"
GVCF_SUFFIX = ".g.vcf.gz"
LOCAL_ARTIFACT_STATUSES = {"DOWNLOADED", "DELETED"}


class JointAnalysisSelectionError(ValueError):
    """The selected datasets cannot safely form a joint-analysis cohort."""


@dataclass(frozen=True)
class JointDataset:
    uuid: str
    sample: str
    gvcf: Path
    study_type: str


def genome_joint_enabled() -> bool:
    return Env.get_bool("JOINT_GENOME_ENABLE", False)


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


def load_joint_settings(config_file: Path, study_type: str) -> Dict[str, Any]:
    """Read the joint settings of one study type from ``joint.yaml``."""
    if study_type not in SUPPORTED_STUDY_TYPES:
        raise JointAnalysisSelectionError(f"Unsupported study type: {study_type}")
    with open(config_file) as f:
        settings = yaml.safe_load(f)[study_type]
    missing = REQUIRED_SETTINGS - set(settings)
    if missing:
        raise JointAnalysisSelectionError(
            f"Joint settings for {study_type} miss {sorted(missing)}"
        )
    return dict(settings)


def reference_marker(workspace: Path) -> Path:
    """File beside (never inside) a workspace recording its reference_id."""
    return workspace.with_name(f"{workspace.name}.reference_id")


def workspace_update_mode(
    workspace: Path, reference_id: str, allow_unmarked: bool = False
) -> bool:
    """Return True to update an existing workspace, False to create it.

    A workspace created with another reference bundle is refused, as is an
    incomplete one (directory without ``callset.json``). A workspace without
    a reference marker is accepted only when ``allow_unmarked`` is set (the
    legacy exome workspace, created before reference tracking).
    """
    marker = reference_marker(workspace)
    recorded = marker.read_text().strip() if marker.is_file() else None
    if recorded is not None and recorded != reference_id:
        raise JointAnalysisSelectionError(
            f"Workspace {workspace} was created with reference {recorded}, "
            f"not {reference_id}"
        )
    if not workspace.exists():
        return False
    if not workspace.joinpath("callset.json").is_file():
        raise JointAnalysisSelectionError(
            f"Workspace {workspace} exists but has no callset.json"
        )
    if recorded is None and not allow_unmarked:
        raise JointAnalysisSelectionError(
            f"Workspace {workspace} has no reference marker {marker.name}"
        )
    return True


def write_reference_marker(workspace: Path, reference_id: str) -> None:
    marker = reference_marker(workspace)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{reference_id}\n")


def exome_joint_entries(
    dataset: Any, input_dir: Path, output_dir: Path
) -> List[JointDataset]:
    """gVCFs of the local exome pipeline, one per sample found in the FASTQs."""
    samples = []
    for f in sorted(input_dir.iterdir()):
        match = re.match(EXOME_FASTQ_PATTERN, f.name)
        if match and match.group(1) not in samples:
            samples.append(match.group(1))
    return [
        JointDataset(
            uuid=dataset.uuid,
            sample=sample,
            gvcf=output_dir.joinpath("gatk_gvcf", f"{sample}_sort_nodup{GVCF_SUFFIX}"),
            study_type="exome",
        )
        for sample in samples
    ]


def genome_joint_entry(dataset: Any) -> JointDataset:
    """The downloaded Omics gVCF of a genome dataset, with its index.

    The sample name is ``<sample>_<dataset_uuid>``: the ``output_gvcf`` sent
    to Omics without suffix, i.e. the read-group ``SM`` inside the gVCF.
    """
    prefix = dataset.omics_output_prefix or ""
    if not prefix.endswith(f"_{dataset.uuid}{GVCF_SUFFIX}"):
        raise JointAnalysisSelectionError(
            f"Dataset {dataset.uuid} has no valid Omics gVCF name"
        )
    gvcfs = [
        artifact
        for artifact in dataset.omics_artifacts.all()
        if artifact.kind == "GVCF"
        and artifact.status in LOCAL_ARTIFACT_STATUSES
        and artifact.local_path
    ]
    if len(gvcfs) != 1:
        raise JointAnalysisSelectionError(
            f"Dataset {dataset.uuid} needs exactly one downloaded gVCF"
        )
    gvcf = Path(gvcfs[0].local_path)
    if gvcf.name != prefix or not gvcf.is_file():
        raise JointAnalysisSelectionError(
            f"Dataset {dataset.uuid}: gVCF {gvcf} is missing or misnamed"
        )
    if not Path(f"{gvcf}.tbi").is_file():
        raise JointAnalysisSelectionError(
            f"Dataset {dataset.uuid}: index {gvcf}.tbi is missing"
        )
    return JointDataset(
        uuid=dataset.uuid,
        sample=prefix[: -len(GVCF_SUFFIX)],
        gvcf=gvcf,
        study_type="genome",
    )


def write_joint_manifest(entries: List[JointDataset], path: Path) -> None:
    """Manifest read by ``Joint_samples.smk``: explicit gVCF path per sample."""
    rows = [[e.sample, e.uuid, str(e.gvcf)] for e in entries]
    DataFrame(rows, columns=["Sample", "Dataset", "Gvcf"]).to_csv(path, index=False)


def write_joint_run_config(
    settings: Dict[str, Any], study_type: str, update: bool, path: Path
) -> None:
    """Resolved per-run Snakemake config, kept in the workdir for audit."""
    joint = dict(settings, study_type=study_type, update=update)
    with open(path, "w") as f:
        yaml.safe_dump({"JOINT": joint}, f, sort_keys=True)
