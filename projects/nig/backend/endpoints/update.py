# from restapi import decorators
from nig.endpoints import NIGEndpoint
from restapi import decorators
from restapi.connectors import celery, neo4j
from restapi.exceptions import NotFound
from restapi.services.authentication import Role

# from restapi.utilities.logs import log


class Update(NIGEndpoint):

    labels = ["admin"]

    @decorators.auth.require_all(Role.ADMIN)
    @decorators.endpoint(
        path="/update",
        summary="Update variants (frequencies)",
        responses={
            200: "Update task successfully executed",
        },
    )
    def get(self):

        graph = neo4j.get_instance()

        # MATCH (v:Variant) SET v:ToBeUpdated
        cypher = "MATCH (v:Variant) WHERE v:ToBeUpdated RETURN count(v) as c"
        result = graph.cypher(cypher)
        count = 0
        for row in result:
            count = int(row[0])

        if count == 0:
            raise NotFound("No variant marked for update")

        c = celery.get_instance()
        task = c.celery_app.send_task("update_annotations")
        return self.response(task.id)
