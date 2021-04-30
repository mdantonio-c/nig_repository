from nig.endpoints import PHENOTYPE_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import BadRequest, NotFound
from restapi.models import Schema, fields
from restapi.rest.definition import Response

# from restapi.utilities.logs import log


class Parent(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)


class Family(NIGEndpoint):

    labels = ["phenotype"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/phenotype/<uuid1>/relationships/<uuid2>",
        summary="Create a new relationship between two phenotypes",
        responses={
            200: "Relationship successfully created",
            400: "Cannot set relationship between the requested phenotypes",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    @decorators.database_transaction
    @decorators.marshal_with(Parent, code=200)
    def post(self, uuid1: str, uuid2: str) -> Response:

        graph = neo4j.get_instance()

        if uuid1 == uuid2:
            raise BadRequest(f"Cannot set relationship between {uuid1} and itself")

        phenotype1 = graph.Phenotype.nodes.get_or_none(uuid=uuid1)
        if phenotype1 is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)

        study = phenotype1.defined_in.single()
        self.verifyStudyAccess(study, error_type="Phenotype", read=False)

        phenotype2 = graph.Phenotype.nodes.get_or_none(uuid=uuid2)
        if phenotype2 is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)

        study = phenotype2.defined_in.single()
        self.verifyStudyAccess(study, error_type="Phenotype", read=False)

        # check parent sex

        if phenotype2.sex == "male":
            relationship = "father"
            phenotype2.son.connect(phenotype1)
            phenotype1.father.connect(phenotype2)

        elif phenotype2.sex == "female":
            relationship = "mother"
            phenotype2.son.connect(phenotype1)
            phenotype1.mother.connect(phenotype2)

        self.log_event(
            self.events.modify,
            phenotype1,
            {"relationship": relationship, "target": phenotype2.uuid},
        )
        res = {"uuid": phenotype2.uuid, "name": phenotype2.name}
        return self.response(res)

    @decorators.auth.require()
    @decorators.endpoint(
        path="/phenotype/<uuid1>/relationships/<uuid2>",
        summary="Delete a relationship between two phenotypes",
        responses={
            200: "Relationship successfully deleted",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    @decorators.database_transaction
    @decorators.marshal_with(Parent, code=200)
    def delete(self, uuid1: str, uuid2: str) -> Response:

        graph = neo4j.get_instance()

        phenotype1 = graph.Phenotype.nodes.get_or_none(uuid=uuid1)
        if phenotype1 is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)

        study = phenotype1.defined_in.single()
        self.verifyStudyAccess(study, error_type="Phenotype", read=False)

        phenotype2 = graph.Phenotype.nodes.get_or_none(uuid=uuid2)
        if phenotype2 is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)

        study = phenotype2.defined_in.single()
        self.verifyStudyAccess(study, error_type="Phenotype", read=False)

        # [1] - FATHER -> [2]
        if phenotype1.father.is_connected(phenotype2):
            phenotype1.father.disconnect(phenotype2)
            # delete son relationship
            phenotype2.son.disconnect(phenotype1)
        # [] - MOTHER -> [2]
        elif phenotype1.mother.is_connected(phenotype2):
            phenotype1.mother.disconnect(phenotype2)
            # delete son relationship
            phenotype2.son.disconnect(phenotype1)

        # [1] <- FATHER - [2]  _or_  [1] <- MOTHER - [2]
        elif phenotype1.son.is_connected(phenotype2):
            phenotype1.son.disconnect(phenotype2)
            # delete mother or father relationship
            if phenotype2.mother.is_connected(phenotype1):
                phenotype2.mother.disconnect(phenotype1)
            if phenotype2.father.is_connected(phenotype1):
                phenotype2.father.disconnect(phenotype1)

        self.log_event(
            self.events.modify,
            phenotype1,
            {"relationship": "removed", "target": phenotype2.uuid},
        )
        res = {"uuid": phenotype2.uuid, "name": phenotype2.name}
        return self.response(res)
