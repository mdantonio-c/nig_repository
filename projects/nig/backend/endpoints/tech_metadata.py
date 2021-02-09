from nig.endpoints import TECHMETA_NOT_FOUND, NIGEndpoint
from nig.time import date_from_string
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import BadRequest, NotFound


class TechnicalMetadata(NIGEndpoint):

    # schema_expose = True
    labels = ["technicals"]

    def validate_input(self, properties, schema):

        if "name" in properties:
            if properties["name"] == "":
                raise BadRequest("Name cannot be empty")

        if "platform" in properties:
            s = properties["platform"]
            allowed = [
                "Illumina",
                "Ion",
                "Pacific Biosciences",
                "Roche 454",
                "SOLiD",
                "SNP-array",
                "Other",
            ]

            if s not in allowed:
                raise BadRequest("Not allowed value for key platform")

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<study_uuid>/technicals",
        summary="Obtain information on a single technical set of metadata",
        responses={
            200: "Technical metadata information successfully retrieved",
            404: "This set of technical metadata cannot be found or you are not authorized to access",
        },
    )
    @decorators.endpoint(
        path="/technical/<technical_uuid>",
        summary="Obtain information on a single technical set of metadata",
        responses={
            200: "Technical metadata information successfully retrieved",
            404: "This set of technical metadata cannot be found or you are not authorized to access",
        },
    )
    def get(self, study_uuid=None, technical_uuid=None):

        graph = neo4j.get_instance()

        if technical_uuid is not None:
            techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=technical_uuid)
            if techmeta is None:
                raise NotFound(TECHMETA_NOT_FOUND)
            study = self.getSingleLinkedNode(techmeta.defined_in)
            self.verifyStudyAccess(study, error_type="Technical Metadata", read=True)
            nodeset = graph.TechnicalMetadata.nodes.filter(uuid=technical_uuid)

        elif study_uuid is not None:
            study = graph.Study.nodes.get_or_none(uuid=study_uuid)
            self.verifyStudyAccess(study, read=True)
            nodeset = study.technicals

        data = []
        for t in nodeset.all():

            techmeta = self.getJsonResponse(t)

            data.append(techmeta)

        return self.response(data)

    @decorators.auth.require()
    # {'custom_parameters': ['Technical']}
    @decorators.endpoint(
        path="/study/<uuid>/technicals",
        summary="Create a new set of technical metadata in a study",
        responses={
            200: "The uuid of the new set of technical metadata",
            404: "This study cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this study",
        },
    )
    @decorators.graph_transactions
    def post(self, uuid):

        graph = neo4j.get_instance()

        v = self.get_input()
        if len(v) == 0:
            raise BadRequest("Empty input")

        schema = self.get_endpoint_custom_definition()
        self.validate_input(v, schema)

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study)
        properties = self.read_properties(schema, v)

        if "sequencing_date" in properties:
            properties["sequencing_date"] = date_from_string(
                properties["sequencing_date"]
            )

        kit = properties.get("enrichment_kit", None)
        if kit is not None and "value" in kit:
            properties["enrichment_kit"] = kit["value"]

        properties["unique_name"] = self.createUniqueIndex(
            study.uuid, properties["name"]
        )
        techmeta = graph.TechnicalMetadata(**properties).save()

        techmeta.defined_in.connect(study)

        return self.response(techmeta.uuid)

    @decorators.auth.require()
    # {'custom_parameters': ['Technical']}
    @decorators.endpoint(
        path="/technical/<uuid>",
        summary="Modify a set of technical metadata",
        responses={
            200: "Technical metadata successfully modified",
            404: "This set of technical metadata cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this set of technical metadata",
        },
    )
    @decorators.graph_transactions
    def put(self, uuid):

        graph = neo4j.get_instance()

        v = self.get_input()
        schema = self.get_endpoint_custom_definition()
        self.validate_input(v, schema)

        techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=uuid)
        if techmeta is None:
            raise NotFound(TECHMETA_NOT_FOUND)
        study = self.getSingleLinkedNode(techmeta.defined_in)
        self.verifyStudyAccess(study, error_type="Technical Metadata")
        if "sequencing_date" in v:
            v["sequencing_date"] = date_from_string(v["sequencing_date"])
        kit = v.get("enrichment_kit", None)
        if kit is not None and "value" in kit:
            v["enrichment_kit"] = kit["value"]

        v["unique_name"] = self.createUniqueIndex(study.uuid, v["name"])
        self.update_properties(techmeta, schema, v)
        techmeta.unique_name = self.createUniqueIndex(study.uuid, techmeta.name)

        techmeta.save()

        return self.empty_response()

    @decorators.auth.require()
    @decorators.endpoint(
        path="/technical/<uuid>",
        summary="Delete a technical set of metadata",
        responses={
            200: "Technical metadata successfully deleted",
            404: "This set of technical metadata cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this set of technical metadata",
        },
    )
    @decorators.graph_transactions
    def delete(self, uuid):

        graph = neo4j.get_instance()

        techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=uuid)
        if techmeta is None:
            raise NotFound(TECHMETA_NOT_FOUND)
        study = self.getSingleLinkedNode(techmeta.defined_in)
        self.verifyStudyAccess(study, error_type="Technical Metadata")

        techmeta.delete()

        return self.empty_response()
