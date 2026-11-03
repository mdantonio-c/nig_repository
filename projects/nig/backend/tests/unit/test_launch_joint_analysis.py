"""J1/J5/J7: launch_joint_analysis runs one homogeneous, typed cohort."""

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import nig
import pytest
import yaml
from nig.services.joint_analysis import JointAnalysisSelectionError
from nig.tasks import launch_joint_analysis as task

JOINT_YAML = Path(nig.__file__).parent / "snakemake" / "joint.yaml"


class Manager:
    def __init__(self, value: Any) -> None:
        self.value = value

    def single(self) -> Any:
        return self.value

    def all(self) -> List[Any]:
        return list(self.value)


class JobManager:
    def __init__(self) -> None:
        self.connected: List[Any] = []

    def connect(self, job: Any) -> None:
        self.connected.append(job)


class Dataset:
    def __init__(self, uuid: str, study_type: str) -> None:
        self.uuid = uuid
        self.parent_study = Manager(SimpleNamespace(uuid="s1", study_type=study_type))
        group = SimpleNamespace(uuid="g1")
        self.ownership = Manager(SimpleNamespace(belongs_to=Manager(group)))
        self.job = JobManager()
        self.joint_analysis: Optional[bool] = None
        self.saved = False
        self.omics_output_prefix: Optional[str] = None
        self.omics_artifacts = Manager([])

    def save(self) -> "Dataset":
        self.saved = True
        return self


class Graph:
    def __init__(self, datasets: List[Dataset]) -> None:
        by_uuid = {d.uuid: d for d in datasets}
        self.jobs: List[Any] = []
        self.Dataset = SimpleNamespace(
            nodes=SimpleNamespace(get_or_none=lambda uuid: by_uuid.get(uuid))
        )

        def joint_job(**props: Any) -> Any:
            job = SimpleNamespace(save=lambda: job, **props)
            self.jobs.append(job)
            return job

        self.JointAnalysisJob = joint_job


class Env:
    def __init__(
        self, tmp_path: Path, monkeypatch: Any, datasets: List[Dataset], genome: bool
    ) -> None:
        self.root = tmp_path
        self.data = tmp_path / "data"
        self.graph = Graph(datasets)
        self.calls: List[Dict[str, Any]] = []
        snakemake_dir = tmp_path / "snakemake"
        snakemake_dir.mkdir()
        (snakemake_dir / "config.yaml").write_text("PARAMS: {}\n")
        (snakemake_dir / "Joint_samples.smk").write_text("# workflow\n")
        # real settings, with outputs moved under the test directory
        settings = yaml.safe_load(JOINT_YAML.read_text())
        for section in settings.values():
            for key in ("workspace", "genotype_dir", "filtered_dir"):
                section[key] = str(self.data) + section[key][len("/data") :]
        (snakemake_dir / "joint.yaml").write_text(yaml.safe_dump(settings))
        self.settings = settings

        monkeypatch.setattr(task, "neo4j", SimpleNamespace(get_instance=lambda: self.graph))
        monkeypatch.setattr(task, "DATA_PATH", self.data)
        monkeypatch.setattr(task, "INPUT_ROOT", self.data / "input")
        monkeypatch.setattr(task, "OUTPUT_ROOT", self.data / "output")
        monkeypatch.setattr(task, "SNAKEMAKE_DIR", snakemake_dir)
        monkeypatch.setattr(task, "genome_joint_enabled", lambda: genome)
        monkeypatch.setattr(
            task, "snakemake", lambda path, **kwargs: self.calls.append(dict(kwargs, path=path))
        )

    def run(self, uuids: List[str], study_type: Optional[str]) -> None:
        fake_task = SimpleNamespace(request=SimpleNamespace(id="task-1"), name="joint")
        inspect.unwrap(task.launch_joint_analysis.__wrapped__)(
            fake_task, uuids, "Joint_samples.smk", True, study_type
        )

    def nothing_created(self) -> bool:
        return not self.graph.jobs and not self.calls and not self.data.exists()


def exome_dataset(env_root: Path, uuid: str, samples: List[str]) -> Dataset:
    dataset = Dataset(uuid, "exome")
    input_dir = env_root / "data" / "input" / "g1" / "s1" / uuid
    input_dir.mkdir(parents=True)
    for sample in samples:
        (input_dir / f"{sample}_R1.fastq.gz").touch()
        (input_dir / f"{sample}_R2.fastq.gz").touch()
    return dataset


def genome_dataset(env_root: Path, uuid: str, tbi: bool = True) -> Dataset:
    dataset = Dataset(uuid, "genome")
    dataset.omics_output_prefix = f"WGS1_{uuid}.g.vcf.gz"
    gvcf = env_root / "omics" / uuid / dataset.omics_output_prefix
    gvcf.parent.mkdir(parents=True)
    gvcf.touch()
    if tbi:
        Path(f"{gvcf}.tbi").touch()
    dataset.omics_artifacts = Manager(
        [SimpleNamespace(kind="GVCF", status="DOWNLOADED", local_path=str(gvcf))]
    )
    return dataset


def run_config(workdir: Path) -> Dict[str, Any]:
    return yaml.safe_load((workdir / "joint_run.yaml").read_text())["JOINT"]


def test_mixed_cohort_is_refused_before_creating_anything(
    tmp_path: Path, monkeypatch: Any
) -> None:
    datasets = [Dataset("e1", "exome"), Dataset("g1", "genome")]
    env = Env(tmp_path, monkeypatch, datasets, genome=True)

    for study_type in ("exome", "genome", None):
        with pytest.raises(JointAnalysisSelectionError):
            env.run(["e1", "g1"], study_type)

    assert env.nothing_created()


def test_missing_dataset_is_refused(tmp_path: Path, monkeypatch: Any) -> None:
    env = Env(tmp_path, monkeypatch, [Dataset("e1", "exome")], genome=False)

    with pytest.raises(JointAnalysisSelectionError):
        env.run(["e1", "unknown"], "exome")
    assert env.nothing_created()


def test_genome_is_refused_while_the_flag_is_off(tmp_path: Path, monkeypatch: Any) -> None:
    datasets = [genome_dataset(tmp_path, "g1")]
    env = Env(tmp_path, monkeypatch, datasets, genome=False)

    with pytest.raises(JointAnalysisSelectionError, match="JOINT_GENOME_ENABLE"):
        env.run(["g1"], "genome")
    assert env.nothing_created()


def test_exome_joint_keeps_its_layout(tmp_path: Path, monkeypatch: Any) -> None:
    d1 = exome_dataset(tmp_path, "d1", ["S1"])
    d2 = exome_dataset(tmp_path, "d2", ["S10"])
    missing = Dataset("d3", "exome")  # no input folder: skipped as before
    env = Env(tmp_path, monkeypatch, [d1, d2, missing], genome=False)

    env.run(["d1", "d2", "d3"], "exome")

    workdir = env.data / "jobs" / "task-1"
    (job,) = env.graph.jobs
    assert (job.uuid, job.study_type, job.reference_id) == (
        "task-1",
        "exome",
        "nig-legacy-grch38p12-dbsnp154-v0",
    )
    out = env.data / "output" / "g1" / "s1"
    assert (workdir / "joint.csv").read_text().splitlines() == [
        "Sample,Dataset,Gvcf",
        f"S1,d1,{out}/d1/gatk_gvcf/S1_sort_nodup.g.vcf.gz",
        f"S10,d2,{out}/d2/gatk_gvcf/S10_sort_nodup.g.vcf.gz",
    ]
    assert not (workdir / "fastq.csv").exists()
    assert run_config(workdir) == dict(
        env.settings["exome"], study_type="exome", update=False
    )
    assert (workdir / "Joint_samples.smk").is_file() and (workdir / "tmp").is_dir()
    assert d1.joint_analysis and d2.joint_analysis and d1.job.connected == [job]
    assert missing.joint_analysis is None and not missing.job.connected
    (call,) = env.calls
    assert call["path"] == workdir / "Joint_samples.smk"
    assert call["workdir"] == workdir
    assert call["configfiles"] == [workdir / "config.yaml", workdir / "joint_run.yaml"]
    assert call["forceall"] is True


def test_existing_unmarked_exome_workspace_is_updated_untouched(
    tmp_path: Path, monkeypatch: Any
) -> None:
    d1 = exome_dataset(tmp_path, "d1", ["S1"])
    env = Env(tmp_path, monkeypatch, [d1], genome=False)
    workspace = Path(env.settings["exome"]["workspace"])
    workspace.mkdir(parents=True)
    (workspace / "callset.json").write_text('{"callsets": []}')

    env.run(["d1"], "exome")

    assert run_config(env.data / "jobs" / "task-1")["update"] is True
    assert [p.name for p in workspace.iterdir()] == ["callset.json"]
    assert not workspace.with_name("gatk_db.reference_id").exists()


def test_genome_joint_uses_bundle_namespace_and_artifacts(
    tmp_path: Path, monkeypatch: Any
) -> None:
    g1 = genome_dataset(tmp_path, "g1")
    env = Env(tmp_path, monkeypatch, [g1], genome=True)

    env.run(["g1"], "genome")

    workdir = env.data / "jobs" / "joint" / "genome" / "task-1"
    (job,) = env.graph.jobs
    assert (job.study_type, job.reference_id) == (
        "genome",
        "nig-grch38p14-dbsnp157-chr-v1",
    )
    gvcf = tmp_path / "omics" / "g1" / "WGS1_g1.g.vcf.gz"
    assert (workdir / "joint.csv").read_text().splitlines() == [
        "Sample,Dataset,Gvcf",
        f"WGS1_g1,g1,{gvcf}",
    ]
    config = run_config(workdir)
    assert config["update"] is False
    assert config["workspace"] == str(env.data / "output/joint/genome/gatk_db")
    marker = env.data / "output/joint/genome/gatk_db.reference_id"
    assert marker.read_text() == "nig-grch38p14-dbsnp157-chr-v1\n"
    assert g1.joint_analysis and g1.job.connected == [job]
    assert env.calls[0]["configfiles"][-1] == workdir / "joint_run.yaml"


def test_genome_without_index_fails_closed(tmp_path: Path, monkeypatch: Any) -> None:
    g1 = genome_dataset(tmp_path, "g1", tbi=False)
    env = Env(tmp_path, monkeypatch, [g1], genome=True)

    with pytest.raises(JointAnalysisSelectionError, match="tbi"):
        env.run(["g1"], "genome")
    assert env.nothing_created()


def test_workspace_of_another_reference_is_refused(
    tmp_path: Path, monkeypatch: Any
) -> None:
    g1 = genome_dataset(tmp_path, "g1")
    env = Env(tmp_path, monkeypatch, [g1], genome=True)
    workspace = Path(env.settings["genome"]["workspace"])
    workspace.mkdir(parents=True)
    (workspace / "callset.json").write_text('{"callsets": []}')
    workspace.with_name("gatk_db.reference_id").write_text("other-bundle\n")

    with pytest.raises(JointAnalysisSelectionError, match="other-bundle"):
        env.run(["g1"], "genome")
    assert not env.graph.jobs and not env.calls
    assert not (env.data / "jobs").exists()
