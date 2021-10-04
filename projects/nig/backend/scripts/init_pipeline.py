import os

from restapi.connectors import celery, neo4j

# get the list of dataset ready to be analysed
graph = neo4j.get_instance()

datasets_to_analise = graph.Dataset.nodes.filter(status="UPLOAD COMPLETED").all()

# get all the dataset uuid
datasets_uuid = [x.uuid for x in datasets_to_analise]

chunks_limit = int(os.environ.get("CHUNKS_LIMIT"))

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
