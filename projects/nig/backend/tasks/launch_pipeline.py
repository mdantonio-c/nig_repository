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
from restapi.utilities.logs import log
from snakemake import snakemake


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def launch_pipeline(
    self: Task,
    dataset_list: List[str],
    snakefile: str = "Single_Sample.smk",
    force: bool = False,
) -> None:
    task_id = self.request.id
    log.info("Start task [{}:{}]", task_id, self.name)
    # create a job node related to the task
    graph = neo4j.get_instance()
    job = graph.Job(uuid=task_id, status="STARTED").save()

    # create a unique workdir for every celery task / and snakemake launch)
    wrkdir = DATA_PATH.joinpath("jobs", task_id)
    wrkdir.mkdir(parents=True, exist_ok=True)
    # copy the files used by snakemake in the work dir
    source_dir = Path("/snakemake")
    for snk_file in source_dir.glob("*"):
        if snk_file.is_file():
            shutil.copy(snk_file, wrkdir)

    # get the file list from the dataset list
    file_list = []
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
        # append the contained files in the file list
        for f in datasetDirectory.iterdir():
            file_list.append(f)
        # mark the dataset as running
        dataset.status = "RUNNING"
        # connect the dataset to the job node
        dataset.job.connect(job)
        dataset.save()

    # create a list of fastq files as csv file: fastq.csv
    fastq = []

    # the pattern is check also in the file upload endpoint. This is an additional check
    pattern = r"([a-zA-Z0-9_-]+)_(R[12]).fastq.gz"
    for filepath in file_list:
        fname = filepath.name
        if match := re.match(pattern, fname):
            file_label = match.group(1)
            fragment = match.group(2)

            # get the input path
            input_path = filepath.parent
            # create the output path
            output_path = OUTPUT_ROOT.joinpath(input_path.relative_to(INPUT_ROOT))
            output_path.mkdir(parents=True, exist_ok=True)
            if not output_path.joinpath(fname).exists():
                output_path.joinpath(fname).symlink_to(filepath)

            # create row for csv
            fastq_row = [file_label, fragment, input_path, output_path]
            fastq.append(fastq_row)
        else:
            log.info(
                "fastq {} should follow correct naming convention: "
                "SampleName_R1/R2.fastq.gz",
                filepath,
            )

    # A dataframe is created
    df = DataFrame(fastq, columns=["Sample", "Frag", "InputPath", "OutputPath"])
    df["Reverse"] = "No"
    df.loc[df.Frag == "R2", "Reverse"] = "Yes"
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

    return None
