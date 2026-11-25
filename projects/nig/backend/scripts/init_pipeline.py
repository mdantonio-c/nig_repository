#!/usr/bin/python3
"""Dispatch datasets ready for analysis to the local Snakemake pipeline.

Note: ``genome`` studies must never be picked up by this
local dispatcher. They are delegated to Omics/Parabricks, dispatched instead by
``init_omics_pipeline.py``. Only datasets belonging to an ``exome`` study are
selected here; datasets with a missing/unexpected ``study_type`` are skipped
(and logged) rather than run locally, since running the wrong pipeline is a
security/data-integrity concern, not just an efficiency one.
"""

from datetime import datetime
from typing import Any, List

import pytz
from restapi.connectors import celery, neo4j
from restapi.env import Env
from restapi.utilities.logs import log

# The only study_type allowed to run on the local Snakemake pipeline.
LOCAL_STUDY_TYPE = "exome"


def select_local_datasets(datasets: List[Any]) -> List[Any]:
    """Filter datasets down to those belonging to a local (exome) study.

    A dataset is excluded (and never queued locally) if it has no parent
    study, or if the parent study's ``study_type`` is not ``"exome"``
    (e.g. ``"genome"``, delegated to Omics).
    """
    selected = []
    for dataset in datasets:
        study = dataset.parent_study.single()
        if study is None:
            log.warning(
                "Dataset {} has no parent study, skipping local dispatch",
                dataset.uuid,
            )
            continue
        if study.study_type != LOCAL_STUDY_TYPE:
            log.info(
                "Dataset {} belongs to a '{}' study, skipping local dispatch",
                dataset.uuid,
                study.study_type,
            )
            continue
        selected.append(dataset)
    return selected


def main() -> None:
    log.info("Starting init pipeline cron")
    # get the list of datasets ready to be analysed
    graph = neo4j.get_instance()

    datasets_to_analise = graph.Dataset.nodes.filter(status="UPLOAD COMPLETED").all()

    # only exome datasets are dispatched locally; genome studies go to Omics
    local_datasets = select_local_datasets(datasets_to_analise)

    # get all the dataset uuid
    datasets_uuid = [x.uuid for x in local_datasets]

    chunks_limit = Env.get_int("CHUNKS_LIMIT", 16)

    for chunk in [
        datasets_uuid[i : i + chunks_limit]
        for i in range(0, len(datasets_uuid), chunks_limit)
    ]:
        log.info("Sending pipeline for datasets: {}", chunk)
        # pass the chunk to the celery task
        c = celery.get_instance()
        task = c.celery_app.send_task(
            "launch_pipeline",
            args=(chunk,),
            countdown=1,
        )
        log.info("{} datasets sent to task {}", len(chunk), task)
        # mark the related datasets as "QUEUED"
        for d in chunk:
            dataset = graph.Dataset.nodes.get_or_none(uuid=d)
            dataset.status = "QUEUED"
            dataset.status_update = datetime.now(pytz.utc)
            dataset.save()

    log.info("Init pipeline cron completed\n")


if __name__ == "__main__":
    main()
