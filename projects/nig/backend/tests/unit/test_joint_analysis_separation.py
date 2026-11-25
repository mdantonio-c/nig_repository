"""Safety tests for study-type-separated joint-analysis preparation."""

from pathlib import Path
from typing import Any, List, Optional

import nig
import pytest
import yaml
from nig.scripts.init_joint_analysis import joint_cohorts
from nig.services.joint_analysis import (
    JointAnalysisSelectionError,
    JointDataset,
    exome_joint_entries,
    genome_joint_entry,
    joint_workdir,
    load_joint_settings,
    reference_marker,
    require_homogeneous,
    select_joint_datasets,
    workspace_update_mode,
    write_joint_manifest,
    write_joint_run_config,
    write_reference_marker,
)

JOINT_YAML = Path(nig.__file__).parent / "snakemake" / "joint.yaml"


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


# --- J1: init script, one task per study type ------------------------------


def test_init_sends_only_exome_when_genome_flag_is_off() -> None:
    datasets = [Dataset("e1", "exome"), Dataset("g1", "genome"), Dataset("e2", "exome")]

    assert joint_cohorts(datasets, genome_enabled=False) == {"exome": ["e1", "e2"]}


def test_init_sends_one_cohort_per_type_when_genome_flag_is_on() -> None:
    datasets = [Dataset("e1", "exome"), Dataset("g1", "genome")]

    assert joint_cohorts(datasets, genome_enabled=True) == {
        "exome": ["e1"],
        "genome": ["g1"],
    }


def test_init_omits_empty_cohorts_and_applies_the_limit() -> None:
    datasets = [Dataset("e1", "exome"), Dataset("e2", "exome"), Dataset("g1", "genome")]

    assert joint_cohorts(datasets, genome_enabled=True, limit=2) == {
        "exome": ["e1", "e2"]
    }
    assert joint_cohorts([], genome_enabled=True) == {}


def test_init_fails_closed_on_untyped_dataset() -> None:
    with pytest.raises(JointAnalysisSelectionError):
        joint_cohorts([Dataset("e1", "exome"), Dataset("x", None)], genome_enabled=True)


# --- J5/J7: per-type settings ------------------------------------------------


def test_exome_settings_keep_the_legacy_joint_unchanged() -> None:
    exome = load_joint_settings(JOINT_YAML, "exome")

    assert exome["reference_id"] == "nig-legacy-grch38p12-dbsnp154-v0"
    assert exome["fasta"] == "/resources/genome/Homo_sapiens_assembly38.fasta"
    assert (
        exome["intervals"]
        == "/resources/hg38_resources/wgs_calling_regions.hg38.interval_list"
    )
    assert exome["workspace"] == "/data/output/gatk_db"
    assert exome["genotype_dir"] == "/data/output/gatk_genotype_gvcf"
    assert exome["filtered_dir"] == "/data/output/gatk_filtered_multisamples"
    assert exome["java_heap"] == "-Xmx88g -Xms10g"
    assert exome["reader_threads"] == 48
    assert exome["batch_size"] == 50
    assert exome["annotations"] == [
        "StandardAnnotation",
        "StandardHCAnnotation",
        "AS_StandardAnnotation",
    ]
    assert exome["allow_unmarked_workspace"] is True


def test_genome_settings_use_the_bundle_and_a_dedicated_namespace() -> None:
    genome = load_joint_settings(JOINT_YAML, "genome")
    bundle = "/resources/reference-bundles/nig-grch38p14-dbsnp157-chr-v1/bundle/"

    assert genome["reference_id"] == "nig-grch38p14-dbsnp157-chr-v1"
    assert genome["fasta"] == bundle + "Homo_sapiens_GRCh38.p14_nig_chr.fasta"
    assert genome["intervals"] == bundle + "wgs_calling_regions.grch38p14_nig_chr.interval_list"
    for key in ("workspace", "genotype_dir", "filtered_dir"):
        assert genome[key].startswith("/data/output/joint/genome/")
    assert genome["allow_unmarked_workspace"] is False


def test_settings_with_missing_keys_are_rejected(tmp_path: Path) -> None:
    config = tmp_path / "joint.yaml"
    config.write_text(yaml.safe_dump({"genome": {"reference_id": "x"}}))

    with pytest.raises(JointAnalysisSelectionError):
        load_joint_settings(config, "genome")
    with pytest.raises(JointAnalysisSelectionError):
        load_joint_settings(JOINT_YAML, "mixed")


# --- reference_id tracking ---------------------------------------------------


def test_missing_workspace_is_created(tmp_path: Path) -> None:
    assert workspace_update_mode(tmp_path / "gatk_db", "ref-1") is False


def test_marker_is_written_beside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "joint" / "genome" / "gatk_db"

    write_reference_marker(workspace, "ref-1")

    assert reference_marker(workspace) == workspace.parent / "gatk_db.reference_id"
    assert reference_marker(workspace).read_text() == "ref-1\n"
    assert not workspace.exists()


def workspace_with_callset(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "callset.json").write_text('{"callsets": []}')
    return path


def test_marked_workspace_with_same_reference_is_updated(tmp_path: Path) -> None:
    workspace = workspace_with_callset(tmp_path / "gatk_db")
    write_reference_marker(workspace, "ref-1")

    assert workspace_update_mode(workspace, "ref-1") is True


def test_workspace_with_another_reference_is_refused(tmp_path: Path) -> None:
    workspace = workspace_with_callset(tmp_path / "gatk_db")
    write_reference_marker(workspace, "ref-old")

    with pytest.raises(JointAnalysisSelectionError, match="ref-old"):
        workspace_update_mode(workspace, "ref-1", allow_unmarked=True)


def test_unmarked_workspace_needs_an_explicit_allowance(tmp_path: Path) -> None:
    workspace = workspace_with_callset(tmp_path / "gatk_db")

    with pytest.raises(JointAnalysisSelectionError):
        workspace_update_mode(workspace, "ref-1")
    # legacy exome workspace: accepted, nothing written inside or beside it
    assert workspace_update_mode(workspace, "ref-1", allow_unmarked=True) is True
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gatk_db"]
    assert [p.name for p in workspace.iterdir()] == ["callset.json"]


def test_incomplete_workspace_is_refused(tmp_path: Path) -> None:
    workspace = tmp_path / "gatk_db"
    workspace.mkdir()

    with pytest.raises(JointAnalysisSelectionError):
        workspace_update_mode(workspace, "ref-1", allow_unmarked=True)


# --- J2/J3: explicit gVCF paths ----------------------------------------------


def test_exome_entries_keep_the_local_gvcf_layout(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for name in ("S1_R1.fastq.gz", "S1_R2.fastq.gz", "S10_R1.fastq.gz", "notes.txt"):
        (input_dir / name).touch()
    output_dir = tmp_path / "output"

    entries = exome_joint_entries(Dataset("d1", "exome"), input_dir, output_dir)

    assert sorted(entries, key=lambda e: e.sample) == [
        JointDataset("d1", "S1", output_dir / "gatk_gvcf/S1_sort_nodup.g.vcf.gz", "exome"),
        JointDataset("d1", "S10", output_dir / "gatk_gvcf/S10_sort_nodup.g.vcf.gz", "exome"),
    ]


class Artifact:
    def __init__(self, kind: str, status: str, local_path: Optional[Path]) -> None:
        self.kind = kind
        self.status = status
        self.local_path = str(local_path) if local_path else None


class Artifacts:
    def __init__(self, values: List[Artifact]) -> None:
        self.values = values

    def all(self) -> List[Artifact]:
        return list(self.values)


def genome_dataset(
    tmp_path: Path, uuid: str = "u1", tbi: bool = True, status: str = "DOWNLOADED"
) -> Dataset:
    dataset = Dataset(uuid, "genome")
    dataset.omics_output_prefix = f"SAMPLE_{uuid}.g.vcf.gz"  # type: ignore[attr-defined]
    gvcf = tmp_path / "omics" / dataset.omics_output_prefix  # type: ignore[attr-defined]
    gvcf.parent.mkdir(parents=True, exist_ok=True)
    gvcf.touch()
    if tbi:
        Path(f"{gvcf}.tbi").touch()
    dataset.omics_artifacts = Artifacts(  # type: ignore[attr-defined]
        [Artifact("GVCF", status, gvcf), Artifact("TBI", status, Path(f"{gvcf}.tbi"))]
    )
    return dataset


@pytest.mark.parametrize("status", ["DOWNLOADED", "DELETED"])
def test_genome_entry_uses_the_downloaded_artifact(tmp_path: Path, status: str) -> None:
    dataset = genome_dataset(tmp_path, status=status)

    entry = genome_joint_entry(dataset)

    assert entry == JointDataset(
        "u1", "SAMPLE_u1", tmp_path / "omics/SAMPLE_u1.g.vcf.gz", "genome"
    )


def test_genome_entry_requires_the_index(tmp_path: Path) -> None:
    with pytest.raises(JointAnalysisSelectionError, match="tbi"):
        genome_joint_entry(genome_dataset(tmp_path, tbi=False))


def test_genome_entry_requires_a_downloaded_gvcf(tmp_path: Path) -> None:
    with pytest.raises(JointAnalysisSelectionError):
        genome_joint_entry(genome_dataset(tmp_path, status="REMOTE"))


def test_genome_entry_requires_the_dataset_uuid_in_the_name(tmp_path: Path) -> None:
    dataset = genome_dataset(tmp_path)
    dataset.omics_output_prefix = "SAMPLE.g.vcf.gz"  # type: ignore[attr-defined]

    with pytest.raises(JointAnalysisSelectionError):
        genome_joint_entry(dataset)


def test_manifest_and_run_config(tmp_path: Path) -> None:
    entries = [JointDataset("u1", "SAMPLE_u1", Path("/x/SAMPLE_u1.g.vcf.gz"), "genome")]
    write_joint_manifest(entries, tmp_path / "joint.csv")
    settings = load_joint_settings(JOINT_YAML, "genome")
    write_joint_run_config(settings, "genome", False, tmp_path / "joint_run.yaml")

    assert (tmp_path / "joint.csv").read_text().splitlines() == [
        "Sample,Dataset,Gvcf",
        "SAMPLE_u1,u1,/x/SAMPLE_u1.g.vcf.gz",
    ]
    run = yaml.safe_load((tmp_path / "joint_run.yaml").read_text())["JOINT"]
    assert run == dict(settings, study_type="genome", update=False)
