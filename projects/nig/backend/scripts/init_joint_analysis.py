#!/usr/bin/python3

import sys

from restapi.connectors import celery, neo4j
from restapi.env import Env
from restapi.utilities.logs import log

log.info("Starting init joint analysis cron")
# get the list of datasets ready to be analysed
graph = neo4j.get_instance()

datasets_to_analise = graph.Dataset.nodes.filter(status="COMPLETED").all()

# to launch this script only on a subset of datasets for testing purposes add the desired lenght of the subset as sys.argv
# for testing purposes: check if we want to analyse only a subset of datasets
if len(sys.argv) > 1:
    all_datasets = [x.uuid for x in datasets_to_analise]
    datasets_uuid = all_datasets[0 : int(sys.argv[1])]
else:
    # get all the dataset uuid
    datasets_uuid = [x.uuid for x in datasets_to_analise]


log.info("Sending joint analysis for datasets: {}", datasets_uuid)

c = celery.get_instance()
task = c.celery_app.send_task(
    "launch_joint_analysis",
    args=(datasets_uuid,),
    countdown=1,
)

log.info("Init Joint analysis cron completed\n")
