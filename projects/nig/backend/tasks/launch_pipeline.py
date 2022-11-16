import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List

import pytz
from juan.qc.applybqsr import ApplyBQSR  # type: ignore
from juan.qc.baserecalibrator import BaseRecalibrator  # type: ignore
from juan.qc.bwa import Bwa  # type: ignore
from juan.qc.fastqc import Fastqc  # type: ignore
from juan.qc.haplotype import HaploType  # type: ignore
from juan.qc.samsort import SamSort  # type: ignore
from nig.endpoints import INPUT_ROOT, OUTPUT_ROOT
from pandas import DataFrame
from restapi.config import DATA_PATH
from restapi.connectors import neo4j
from restapi.connectors.celery import CeleryExt, Task
from restapi.connectors.smtp.notifications import send_notification
from restapi.utilities.logs import log
from snakemake import snakemake


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def launch_pipeline(
    self: Task[[List[str], str, bool], None],
    dataset_list: List[str],
    snakefile: str = "Single_Sample.smk",
    force: bool = False,
) -> None:
    task_id = self.request.id
    log.info("Start task [{}:{}]", task_id, self.name)
    # create a job node related to the task
    graph = neo4j.get_instance()
    job = graph.Job(uuid=task_id).save()

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
    # the pattern is check also in the file upload endpoint. This is an additional check
    pattern = r"([a-zA-Z0-9_-]+)_(R[12]).fastq.gz"
    analized_datasets = []
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
        dataset_files = []
        for f in datasetDirectory.iterdir():
            # check if the pattern is respected
            fname = f.name
            if re.match(pattern, fname):
                dataset_files.append(f)
            else:
                log.info(
                    "fastq {} should follow correct naming convention: "
                    "SampleName_R1/R2.fastq.gz",
                    f,
                )
                continue
        # check if in case of a single file it is of R1 type
        if len(dataset_files) == 1:
            fname = dataset_files[0].name
            match = re.match(pattern, fname)
            if match and match.group(2) == "R2":
                # mark the dataset as error
                msg = "R1 file is missing"
                dataset.status = "ERROR"
                dataset.error_message = msg
                dataset.status_update = datetime.now(pytz.utc)
                # connect the dataset to the job node
                dataset.job.connect(job, {"status": "ERROR", "error_message": msg})
                dataset.save()
                continue
        if dataset_files:
            for f in dataset_files:
                # append the contained files in the file list
                file_list.append(f)
        # mark the dataset as running
        dataset.status = "RUNNING"
        dataset.status_update = datetime.now(pytz.utc)
        # connect the dataset to the job node
        dataset.job.connect(job, {"status": "RUNNING"})
        dataset.save()
        analized_datasets.append(d)

    # create a list of fastq files as csv file: fastq.csv
    fastq = []

    for filepath in file_list:
        fname = filepath.name
        match = re.match(pattern, fname)
        file_label = None
        fragment = None
        if match:
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

    # check the status of the analysed datasets
    input_parameter_path = "/code/juan/template_recaldat.log"
    for d in analized_datasets:
        # get the output path
        dataset = graph.Dataset.nodes.get_or_none(uuid=d)
        if not dataset:
            log.warning(f"no dataset with id {d} was found")
            continue
        owner = dataset.ownership.single()
        group = owner.belongs_to.single()
        study = dataset.parent_study.single()
        output_path = OUTPUT_ROOT.joinpath(group.uuid, study.uuid, dataset.uuid)

        # get the name of the sample
        sample = "N/A"
        for f in dataset.files.all():
            sample = re.findall(pattern, f.name)[0][0]
            break

        check_list = [
            "Fastqc",
            "Bwa",
            "SamSort",
            "BaseRecalibrator",
            "ApplyBQSR",
            "HaploType",
        ]
        check_passed = None
        error_message = None
        try:
            # log.info(f"checking for sample {sample} in {output_path}")
            # check all the logs
            Fastqc(path=f"{output_path}/fastqc/", sample=sample).check_log()
            check_passed = "Fastqc"
            Bwa(
                path=f"{output_path}/bwa/", sample=sample, table_path=fastq_csv_file
            ).check_log()
            check_passed = "Bwa"
            SamSort(
                path=f"{output_path}/bwa/", sample=sample, table_path=fastq_csv_file
            ).check_log()
            check_passed = "SamSort"
            BaseRecalibrator(
                path=f"{output_path}/gatk_bsr/",
                sample=sample,
                table_path=fastq_csv_file,
                input_parameter_path=input_parameter_path,
            ).check_log(check_final_section=False)
            # check_final_section is excluded for now because raises an exception that should be a warning
            check_passed = "BaseRecalibrator"
            ApplyBQSR(
                path=f"{output_path}/gatk_bsr/",
                sample=sample,
                input_parameter_path=input_parameter_path,
            ).check_log(progressmeter_analysis=False, score=False)
            # progressmeter_analysis and score are excluded for now because raise an index out of range exception
            check_passed = "ApplyBQSR"
            HaploType(
                path=f"{output_path}/gatk_gvcf/",
                sample=sample,
                table_path=fastq_csv_file,
            ).check_log()
            check_passed = "HaploType"

            # if all the checks are passed set the dataset status as COMPLETED
            dataset_status = "COMPLETED"
        except Exception as exc:
            # get the check that raised the exception
            if check_passed:
                last_checked = check_list.index(check_passed)
                check_failed_index = last_checked + 1
            else:
                check_failed_index = 0
            error_message = f"Step {check_list[check_failed_index]}: {exc}"
            # log.error(error_message)

            # if the datasets has not passed all the checks its status will be ERROR
            dataset_status = "ERROR"

        # update the dataset status in the db
        dataset.status = dataset_status
        dataset.status_update = datetime.now(pytz.utc)
        if error_message:
            dataset.error_message = error_message
        dataset.save()
        # log.info(f"set status for dataset {d} as {dataset_status}")

        # update the job relationship
        rel = dataset.job.relationship(job)
        rel.status = dataset_status
        if error_message:
            rel.error_message = error_message
        rel.save()

        if dataset_status == "ERROR":
            # send notification email
            send_notification(
                subject="A dataset analysis ended in an error",
                template="dataset_error.html",
                to_address=None,
                data={
                    "dataset_id": dataset.uuid,
                    "dataset_name": dataset.name,
                    "study_id": study.uuid,
                    "study_name": study.name,
                    "error_message": error_message,
                    "output_path": output_path,
                    "job_path": wrkdir,
                },
            )

    log.info(f"check for job {task_id} completed")

    return None
