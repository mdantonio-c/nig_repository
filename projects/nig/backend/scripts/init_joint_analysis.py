#!/usr/bin/python3
"""Send the joint analyses of the COMPLETED datasets, one task per study type.

Exome and genome cohorts are never aggregated: each type gets its own
``launch_joint_analysis`` task. The genome cohort is sent only with
``JOINT_GENOME_ENABLE=1``; with the default (0) only the exome joint is sent.
A dataset whose study has no supported study_type stops the script (fail
closed, nothing is sent).

Usage: init_joint_analysis.py [N]  (N: only the first N datasets, for tests)
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml
from nig.services.joint_analysis import genome_joint_enabled, select_joint_datasets
from restapi.connectors import celery, neo4j
from restapi.utilities.logs import log


def joint_cohorts(
    datasets: Sequence[Any], genome_enabled: bool, limit: Optional[int] = None
) -> Dict[str, List[str]]:
    """Dataset uuids to send per study type; empty and disabled types omitted."""
    if limit is not None:
        datasets = datasets[0:limit]
    cohorts = select_joint_datasets(datasets)
    if cohorts["genome"] and not genome_enabled:
        log.info(
            "JOINT_GENOME_ENABLE is off, genome joint analysis not sent for {} datasets",
            len(cohorts["genome"]),
        )
        cohorts["genome"] = []
    return {
        study_type: [d.uuid for d in members]
        for study_type, members in cohorts.items()
        if members
    }


def main() -> None:
    log.info("Starting init joint analysis cron")
    # get the list of datasets ready to be analysed
    graph = neo4j.get_instance()
    datasets_to_analise = graph.Dataset.nodes.filter(status="COMPLETED").all()

    # to launch this script only on a subset of datasets for testing purposes
    # add the desired lenght of the subset as sys.argv
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    cohorts = joint_cohorts(datasets_to_analise, genome_joint_enabled(), limit)

    # check if the update param is true or false (in order to check if
    # snakemake needs to be forced)
    config_file = Path("/snakemake").joinpath("config.yaml")
    with open(config_file) as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    force = config["UPDATE"]["GDBI"]

    c = celery.get_instance()
    for study_type, datasets_uuid in cohorts.items():
        log.info(
            "Sending {} joint analysis for datasets: {}", study_type, datasets_uuid
        )
        c.celery_app.send_task(
            "launch_joint_analysis",
            args=(datasets_uuid, "Joint_samples.smk", force, study_type),
            countdown=1,
        )

    log.info("Init Joint analysis cron completed\n")


if __name__ == "__main__":
    main()
