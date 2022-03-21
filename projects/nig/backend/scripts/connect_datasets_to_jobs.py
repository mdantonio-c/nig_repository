import csv
from datetime import datetime, timezone
from pathlib import Path

from restapi.config import DATA_PATH
from restapi.connectors import neo4j
from restapi.utilities.logs import log

# get the name of all the jobs by the jobs folders
jobs_root_dir = DATA_PATH.joinpath("jobs")

jobs_dirs = []

# get a list of all job dirs
for d in jobs_root_dir.iterdir():
    if d.is_dir():
        jobs_dirs.append(d)

graph = neo4j.get_instance()
for job in jobs_dirs:
    job_uuid = job.name
    # check if the job exists in the db
    job_node = graph.Job.nodes.get_or_none(uuid=job_uuid)
    if job_node:
        # the job node already exists
        log.info(f"node for job {job_uuid} already exists")
        continue
    # get the creation date of the job
    csv_file = job.joinpath("fastq.csv")
    if not csv_file.is_file():
        log.error(f"no csv file in {job}")
        continue
    creation_time = datetime.fromtimestamp(csv_file.stat().st_mtime, tz=timezone.utc)
    # create the node for the job
    job_node = graph.Job(uuid=job_uuid, created=creation_time).save()
    log.info(f"Job node with uuid {job_uuid} successfully created")

    # get the dataset list related to the job
    dataset_list = []
    with open(csv_file) as file:
        csv_reader = csv.DictReader(file, delimiter=",")
        for row in csv_reader:
            input_path = Path(row["InputPath"])
            dataset_uuid = input_path.name
            dataset_list.append(dataset_uuid)

    # link the datasets to the job
    for ds in dataset_list:
        dataset = graph.Dataset.nodes.get_or_none(uuid=ds)
        if not dataset:
            log.error(f"job {job_uuid}: dataset {ds} not found")
            continue
        dataset.job.connect(job_node)
        dataset.save()
        log.info(f"dataset {ds} successfully linked to job {job_uuid}")
