import os
import re
import shutil
from pathlib import Path
from typing import List

from celery.app.task import Task
from nig.endpoints import INPUT_ROOT, OUTPUT_ROOT
from pandas import DataFrame
from restapi.config import DATA_PATH
from restapi.connectors import neo4j
from restapi.connectors.celery import CeleryExt
from restapi.connectors.smtp.notifications import send_notification
from restapi.utilities.logs import log
from snakemake import snakemake


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def launch_joint_analysis(
    self: Task,
    dataset_list: List[str],
    snakefile: str = "Joint_samples.smk",
    force: bool = False,
) -> None:
    task_id = self.request.id
    log.info("Start joint analysis task [{}:{}]", task_id, self.name)
    # create a job node related to the task
    graph = neo4j.get_instance()
    job = graph.JointAnalysisJob(uuid=task_id).save()

    # create a unique workdir for every celery task / and snakemake launch)
    wrkdir = DATA_PATH.joinpath("jobs", task_id)
    wrkdir.mkdir(parents=True, exist_ok=True)
    # copy the files used by snakemake in the work dir
    source_dir = Path("/snakemake")
    for snk_file in source_dir.glob("*"):
        if snk_file.is_file():
            shutil.copy(snk_file, wrkdir)

    # get the file list from the dataset list
    pattern = r"([a-zA-Z0-9_-]+)_(R[12]).fastq.gz"
    fastq = []
    for d in dataset_list:
        # get the path of the dataset directory
        dataset = graph.Dataset.nodes.get_or_none(uuid=d)
        owner = dataset.ownership.single()
        group = owner.belongs_to.single()
        study = dataset.parent_study.single()
        datasetDirectory = INPUT_ROOT.joinpath(group.uuid, study.uuid, dataset.uuid)
        # check if the directory exists
        if not datasetDirectory.exists():
            # an error should be raised?
            log.warning("Folder for dataset {} not found", d)
            continue

        for f in datasetDirectory.iterdir():
            fname = f.name
            match = re.match(pattern, fname)
            file_label = None
            if match:
                file_label = match.group(1)
            output_path = OUTPUT_ROOT.joinpath(datasetDirectory.relative_to(INPUT_ROOT))
            fastq_row = [file_label, output_path]
            fastq.append(fastq_row)

        # mark that a joint analysis has been launched on this dataset
        dataset.joint_analysis = True
        # connect the dataset to the job node
        dataset.job.connect(job)
        dataset.save()

    # A dataframe is created
    df = DataFrame(fastq, columns=["Sample", "OutputPath"])

    fastq_csv_file = wrkdir.joinpath("fastq.csv")
    df.to_csv(fastq_csv_file, index=False)
    log.info("*************************************")
    log.info("New file {} is now created", fastq_csv_file)
    log.info("Total Number Of Fastq identified:{}\n", df.shape[0])

    # Launch snakemake
    config = [wrkdir.joinpath("config.yaml")]

    cores = os.cpu_count()
    log.info("Calling Snakemake with {} cores", cores)
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
