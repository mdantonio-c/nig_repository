from typing import Any, Optional

import pytz
from nig.endpoints import TECHMETA_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import BadRequest, NotFound
from restapi.models import Schema, fields, validate
from restapi.rest.definition import Response
from restapi.utilities.logs import log

PLATFORMS = [
    "Illumina",
    "Ion",
    "Pacific Biosciences",
    "Roche 454",
    "SOLiD",
    "SNP-array",
    "Other",
]


class TechmetaInputSchema(Schema):
    name = fields.Str(required=True)
    sequencing_date = fields.DateTime("%d/%m/%Y")
    platform = fields.Str(validate=validate.OneOf(PLATFORMS))
    enrichment_kit = fields.Str()


class TechmetaPutSchema(Schema):
    name = fields.Str(required=False)
    sequencing_date = fields.DateTime("%d/%m/%Y")
    platform = fields.Str(validate=validate.OneOf(PLATFORMS))
    enrichment_kit = fields.Str()


class TechmetaOutputSchema(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    sequencing_date = fields.DateTime("%d/%m/%Y")
    platform = fields.Str()
    enrichment_kit = fields.Str()


class TechnicalMetadata(NIGEndpoint):

    # schema_expose = True
    labels = ["technicals"]

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
    @decorators.marshal_with(TechmetaOutputSchema(many=True), code=200)
    def get(
        self, study_uuid: Optional[str] = None, technical_uuid: Optional[str] = None
    ) -> Response:

        graph = neo4j.get_instance()

        if technical_uuid is not None:
            techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=technical_uuid)
            if techmeta is None:
                raise NotFound(TECHMETA_NOT_FOUND)
            study = techmeta.defined_in.single()
            self.verifyStudyAccess(study, error_type="Technical Metadata", read=True)
            nodeset = graph.TechnicalMetadata.nodes.filter(uuid=technical_uuid)

        elif study_uuid is not None:
            study = graph.Study.nodes.get_or_none(uuid=study_uuid)
            self.verifyStudyAccess(study, read=True)
            nodeset = study.technicals

        data = []
        for t in nodeset.all():

            techmeta_el = {
                "uuid": t.uuid,
                "name": t.name,
                "sequencing_date": t.sequencing_date,
                "platform": t.platform,
                "enrichment_kit": t.enrichment_kit,
            }
            data.append(techmeta_el)

        if technical_uuid is not None:
            self.log_event(self.events.access, techmeta)

        return self.response(data)

    @decorators.auth.require()
    # {'custom_parameters': ['Technical']}
    @decorators.endpoint(
        path="/study/<uuid>/technicals",
        summary="Create a new set of technical metadata in a study",
        responses={
            200: "The uuid of the new set of technical metadata",
            404: "This study cannot be found or you are not authorized to access",
        },
    )
    @decorators.graph_transactions
    @decorators.use_kwargs(TechmetaInputSchema)
    def post(self, uuid: str, **kwargs: Any) -> Response:

        graph = neo4j.get_instance()

        # parse date
        seq_date_to_parse = kwargs.get("sequencing_date", None)
        if seq_date_to_parse:
            if seq_date_to_parse.tzinfo is None:
                parsed_date = pytz.utc.localize(seq_date_to_parse)
                kwargs["sequencing_date"] = parsed_date

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study)

        # kit = properties.get("enrichment_kit", None)
        # if kit is not None and "value" in kit:
        #     properties["enrichment_kit"] = kit["value"]

        techmeta = graph.TechnicalMetadata(**kwargs).save()

        techmeta.defined_in.connect(study)

        self.log_event(self.events.create, techmeta, kwargs)

        return self.response(techmeta.uuid)

    @decorators.auth.require()
    # {'custom_parameters': ['Technical']}
    @decorators.endpoint(
        path="/technical/<uuid>",
        summary="Modify a set of technical metadata",
        responses={
            200: "Technical metadata successfully modified",
            404: "This set of technical metadata cannot be found or you are not authorized to access",
        },
    )
    @decorators.graph_transactions
    @decorators.use_kwargs(TechmetaPutSchema)
    def put(self, uuid: str, **kwargs: Any) -> Response:

        graph = neo4j.get_instance()

        techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=uuid)
        if techmeta is None:
            raise NotFound(TECHMETA_NOT_FOUND)
        study = techmeta.defined_in.single()
        self.verifyStudyAccess(study, error_type="Technical Metadata")

        # kit = v.get("enrichment_kit", None)
        # if kit is not None and "value" in kit:
        #     v["enrichment_kit"] = kit["value"]

        # parse date
        seq_date_to_parse = kwargs.get("sequencing_date", None)
        if seq_date_to_parse:
            if seq_date_to_parse.tzinfo is None:
                parsed_date = pytz.utc.localize(seq_date_to_parse)
                kwargs["sequencing_date"] = parsed_date

        self.auth.db.update_properties(techmeta, kwargs)
        techmeta.save()

        self.log_event(self.events.modify, techmeta, kwargs)

        return self.empty_response()

    @decorators.auth.require()
    @decorators.endpoint(
        path="/technical/<uuid>",
        summary="Delete a technical set of metadata",
        responses={
            200: "Technical metadata successfully deleted",
            404: "This set of technical metadata cannot be found or you are not authorized to access",
        },
    )
    @decorators.graph_transactions
    def delete(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=uuid)
        if techmeta is None:
            raise NotFound(TECHMETA_NOT_FOUND)
        study = techmeta.defined_in.single()
        self.verifyStudyAccess(study, error_type="Technical Metadata")

        techmeta.delete()

        self.log_event(self.events.delete, techmeta)

        return self.empty_response()
