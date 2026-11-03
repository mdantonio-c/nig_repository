import os
import shutil
from pathlib import Path
from typing import List, Optional

from nig.endpoints import INPUT_ROOT, OUTPUT_ROOT
from nig.services.joint_analysis import (
    JOINT_CONFIG_FILE,
    JOINT_MANIFEST_FILE,
    JOINT_RUN_CONFIG_FILE,
    JointAnalysisSelectionError,
    JointDataset,
    exome_joint_entries,
    genome_joint_enabled,
    genome_joint_entry,
    joint_workdir,
    load_joint_settings,
    require_homogeneous,
    workspace_update_mode,
    write_joint_manifest,
    write_joint_run_config,
    write_reference_marker,
)
from restapi.config import DATA_PATH
from restapi.connectors import neo4j
from restapi.connectors.celery import CeleryExt, Task
from restapi.connectors.smtp.notifications import send_notification
from restapi.utilities.logs import log
from snakemake import snakemake

SNAKEMAKE_DIR = Path("/snakemake")


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def launch_joint_analysis(
    self: Task[[List[str], str, bool, Optional[str]], None],
    dataset_list: List[str],
    snakefile: str = "Joint_samples.smk",
    force: bool = False,
    study_type: Optional[str] = None,
) -> None:
    task_id = self.request.id
    log.info("Start {} joint analysis task [{}:{}]", study_type, task_id, self.name)
    graph = neo4j.get_instance()

    # validate the whole cohort before creating anything (fail closed)
    if study_type is None:
        raise JointAnalysisSelectionError("Joint analysis requires a study type")
    datasets = []
    for d in dataset_list:
        dataset = graph.Dataset.nodes.get_or_none(uuid=d)
        if dataset is None:
            raise JointAnalysisSelectionError(f"Dataset {d} not found")
        datasets.append(dataset)
    require_homogeneous(datasets, study_type)
    if study_type == "genome" and not genome_joint_enabled():
        raise JointAnalysisSelectionError(
            "JOINT_GENOME_ENABLE is off, genome joint analysis not executed"
        )

    settings = load_joint_settings(SNAKEMAKE_DIR.joinpath(JOINT_CONFIG_FILE), study_type)
    reference_id = settings["reference_id"]
    workspace = Path(settings["workspace"])
    update = workspace_update_mode(
        workspace, reference_id, settings["allow_unmarked_workspace"]
    )

    # gVCF of every sample, with its explicit path
    entries: List[JointDataset] = []
    analysed = []
    for dataset in datasets:
        if study_type == "genome":
            entries.append(genome_joint_entry(dataset))
            analysed.append(dataset)
            continue
        # get the path of the dataset directory
        owner = dataset.ownership.single()
        group = owner.belongs_to.single()
        study = dataset.parent_study.single()
        datasetDirectory = INPUT_ROOT.joinpath(group.uuid, study.uuid, dataset.uuid)
        # check if the directory exists
        if not datasetDirectory.exists():
            # an error should be raised?
            log.warning("Folder for dataset {} not found", dataset.uuid)
            continue
        output_path = OUTPUT_ROOT.joinpath(datasetDirectory.relative_to(INPUT_ROOT))
        entries.extend(exome_joint_entries(dataset, datasetDirectory, output_path))
        analysed.append(dataset)

    # create a job node related to the task
    job = graph.JointAnalysisJob(
        uuid=task_id, study_type=study_type, reference_id=reference_id
    ).save()

    # create a unique workdir for every celery task / and snakemake launch)
    if study_type == "exome":
        # exome keeps its historical location
        wrkdir = DATA_PATH.joinpath("jobs", task_id)
    else:
        wrkdir = joint_workdir(DATA_PATH, task_id, study_type)
    wrkdir.mkdir(parents=True, exist_ok=True)
    # copy the files used by snakemake in the work dir
    for snk_file in SNAKEMAKE_DIR.glob("*"):
        if snk_file.is_file():
            shutil.copy(snk_file, wrkdir)

    # create the tmp dir used by gatk
    tmp_dir = wrkdir.joinpath("tmp")
    if not tmp_dir.exists():
        tmp_dir.mkdir()

    for dataset in analysed:
        # mark that a joint analysis has been launched on this dataset
        dataset.joint_analysis = True
        # connect the dataset to the job node
        dataset.job.connect(job)
        dataset.save()

    manifest = wrkdir.joinpath(JOINT_MANIFEST_FILE)
    write_joint_manifest(entries, manifest)
    run_config = wrkdir.joinpath(JOINT_RUN_CONFIG_FILE)
    write_joint_run_config(settings, study_type, update, run_config)
    log.info("*************************************")
    log.info("New file {} is now created", manifest)
    log.info("Total Number Of gVCF identified:{}\n", len(entries))

    if not update:
        # record the bundle beside the workspace that is going to be created
        write_reference_marker(workspace, reference_id)

    # Launch snakemake
    config = [wrkdir.joinpath("config.yaml"), run_config]

    cores = os.cpu_count()
    log.info(
        "Calling Snakemake with {} cores, forceall {}, update {}, reference {}",
        cores,
        force,
        update,
        reference_id,
    )
    snakefile_path = wrkdir.joinpath(snakefile)

    # https://snakemake.readthedocs.io/en/stable/api_reference/snakemake.html
    snakemake(
        snakefile_path,
        cores=cores,
        workdir=wrkdir,
        configfiles=config,
        forceall=force,
        # Go on with independent jobs if a job fails. (default: False)
        keepgoing=True,
        # force the re-creation of incomplete files (default False)
        force_incomplete=True,
        # lock the working directory when executing the workflow (default True)
        lock=False,
    )

    log.info(f"job {task_id} completed")

    return None
