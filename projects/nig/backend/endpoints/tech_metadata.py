from datetime import datetime
from typing import Any

import pytz
from nig.endpoints import TECHMETA_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import NotFound
from restapi.models import ISO8601UTC, Schema, fields, validate
from restapi.rest.definition import Response

# from restapi.utilities.logs import log

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
    sequencing_date = fields.DateTime(format=ISO8601UTC)
    platform = fields.Str(validate=validate.OneOf(PLATFORMS))
    enrichment_kit = fields.Str()


class TechmetaPutSchema(Schema):
    name = fields.Str(required=False)
    sequencing_date = fields.DateTime(format=ISO8601UTC)
    platform = fields.Str(validate=validate.OneOf(PLATFORMS))
    enrichment_kit = fields.Str()


class TechmetaOutputSchema(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    sequencing_date = fields.DateTime(format=ISO8601UTC)
    platform = fields.Str()
    enrichment_kit = fields.Str()


class TechnicalMetadatas(NIGEndpoint):

    # schema_expose = True
    labels = ["technicals"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<uuid>/technicals",
        summary="Obtain information on a single technical set of metadata",
        responses={
            200: "Technical metadata information successfully retrieved",
            404: "This set of technical metadata cannot be found or you are not authorized to access",
        },
    )
    @decorators.marshal_with(TechmetaOutputSchema(many=True), code=200)
    def get(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, read=True)
        nodeset = study.technicals

        data = []
        for techmeta in nodeset.all():

            data.append(techmeta)

        return self.response(data)


class TechnicalMetadata(NIGEndpoint):
    @staticmethod
    def check_timezone(date: datetime) -> datetime:
        if date.tzinfo is None:
            date = pytz.utc.localize(date)
        return date

    labels = ["technicals"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/technical/<uuid>",
        summary="Obtain information on a single technical set of metadata",
        responses={
            200: "Technical metadata information successfully retrieved",
            404: "This set of technical metadata cannot be found or you are not authorized to access",
        },
    )
    @decorators.marshal_with(TechmetaOutputSchema, code=200)
    def get(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=uuid)
        if not techmeta:
            raise NotFound(TECHMETA_NOT_FOUND)
        study = techmeta.defined_in.single()
        self.verifyStudyAccess(study, error_type="Technical Metadata", read=True)

        self.log_event(self.events.access, techmeta)

        return self.response(techmeta)

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<uuid>/technicals",
        summary="Create a new set of technical metadata in a study",
        responses={
            200: "The uuid of the new set of technical metadata",
            404: "This study cannot be found or you are not authorized to access",
        },
    )
    @decorators.database_transaction
    @decorators.use_kwargs(TechmetaInputSchema)
    def post(self, uuid: str, **kwargs: Any) -> Response:

        graph = neo4j.get_instance()

        # parse date
        if "sequencing_date" in kwargs:
            kwargs["sequencing_date"] = self.check_timezone(kwargs["sequencing_date"])

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
    @decorators.endpoint(
        path="/technical/<uuid>",
        summary="Modify a set of technical metadata",
        responses={
            200: "Technical metadata successfully modified",
            404: "This set of technical metadata cannot be found or you are not authorized to access",
        },
    )
    @decorators.database_transaction
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
        if "sequencing_date" in kwargs:
            kwargs["sequencing_date"] = self.check_timezone(kwargs["sequencing_date"])

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
    @decorators.database_transaction
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
