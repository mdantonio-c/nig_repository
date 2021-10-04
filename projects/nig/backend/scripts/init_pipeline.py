#!/usr/bin/python3

from restapi.connectors import celery, neo4j
from restapi.env import Env

# get the list of datasets ready to be analysed
graph = neo4j.get_instance()

datasets_to_analise = graph.Dataset.nodes.filter(status="UPLOAD COMPLETED").all()

# get all the dataset uuid
datasets_uuid = [x.uuid for x in datasets_to_analise]

chunks_limit = Env.get_int("CHUNKS_LIMIT", 16)

for chunk in [
    datasets_uuid[i : i + chunks_limit]
    for i in range(0, len(datasets_uuid), chunks_limit)
]:
    # pass the chunk to the celery task
    c = celery.get_instance()
    task = c.celery_app.send_task(
        "launch_pipeline",
        args=(chunk,),
        countdown=1,
    )
    # mark the related datasets as "QUEUED"
    for d in chunk:
        dataset = graph.Dataset.nodes.get_or_none(uuid=d)
        dataset.status = "QUEUED"
        dataset.save()
