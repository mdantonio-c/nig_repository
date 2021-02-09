from nig.endpoints import PHENOTYPE_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import BadRequest, NotFound


class Family(NIGEndpoint):

    labels = ["phenotype"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/phenotype/<uuid1>/relationships/<uuid2>",
        summary="Create a new relationship between two phenotypes",
        responses={
            200: "Relationship successfully created",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    @decorators.graph_transactions
    def post(self, uuid1, uuid2):

        graph = neo4j.get_instance()
        v = self.get_input()
        allowed = ["father", "mother"]

        if "type" not in v:
            return self.response(
                "Missing relationship type, allowed values are: %s" % allowed
            )

        relationship = v["type"]

        if uuid1 == uuid2:
            raise BadRequest(f"Cannot set relationship between {uuid1} and itself")

        if relationship not in allowed:
            raise BadRequest(f"Unknown relationship, allowed values are: {allowed}")

        phenotype1 = graph.Phenotype.nodes.get_or_none(uuid=uuid1)
        if phenotype1 is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)

        study = self.getSingleLinkedNode(phenotype1.defined_in)
        self.verifyStudyAccess(study, error_type="Phenotype", read=True)

        phenotype2 = graph.Phenotype.nodes.get_or_none(uuid=uuid2)
        if phenotype2 is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)

        study = self.getSingleLinkedNode(phenotype2.defined_in)
        self.verifyStudyAccess(study, error_type="Phenotype", read=True)

        if relationship == "father":
            phenotype2.son.connect(phenotype1)
            phenotype1.father.connect(phenotype2)

        if relationship == "mother":
            phenotype2.son.connect(phenotype1)
            phenotype1.mother.connect(phenotype2)

        return self.empty_response()

    @decorators.auth.require()
    @decorators.endpoint(
        path="/phenotype/<uuid1>/relationships/<uuid2>",
        summary="Delete a relationship between two phenotypes",
        responses={
            200: "Relationship successfully deleted",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    @decorators.graph_transactions
    def delete(self, uuid1, uuid2):

        graph = neo4j.get_instance()
        v = self.get_input()
        allowed = ["father", "mother"]

        if "type" not in v:
            raise BadRequest(
                f"Missing relationship type, allowed values are: {allowed}"
            )

        relationship = v["type"]

        phenotype1 = graph.Phenotype.nodes.get_or_none(uuid=uuid1)
        if phenotype1 is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)

        study = self.getSingleLinkedNode(phenotype1.defined_in)
        self.verifyStudyAccess(study, error_type="Phenotype", read=True)

        phenotype2 = graph.Phenotype.nodes.get_or_none(uuid=uuid2)
        if phenotype2 is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)

        study = self.getSingleLinkedNode(phenotype2.defined_in)
        self.verifyStudyAccess(study, error_type="Phenotype", read=True)

        # [1] - FATHER -> [2]
        if relationship == "father":
            if phenotype1.father.is_connected(phenotype2):
                phenotype1.father.disconnect(phenotype2)
            if phenotype2.son.is_connected(phenotype1):
                phenotype2.son.disconnect(phenotype1)

        # [1] - MOTHER -> [2]
        if relationship == "mother":
            if phenotype1.mother.is_connected(phenotype2):
                phenotype1.mother.disconnect(phenotype2)
            if phenotype2.son.is_connected(phenotype1):
                phenotype2.son.disconnect(phenotype1)

        # [1] <- FATHER - [2]  _or_  [1] <- MOTHER - [2]
        if relationship == "son":
            if phenotype1.son.is_connected(phenotype2):
                phenotype1.son.disconnect(phenotype2)
            if phenotype2.mother.is_connected(phenotype1):
                phenotype2.mother.disconnect(phenotype1)
            if phenotype2.father.is_connected(phenotype1):
                phenotype2.father.disconnect(phenotype1)

        return self.empty_response()
