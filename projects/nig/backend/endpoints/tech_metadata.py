from typing import Any, Dict, List, Type, Union

from marshmallow import ValidationError, pre_load, validates_schema
from nig.endpoints import TECHMETA_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.customizer import FlaskRequest
from restapi.exceptions import BadRequest, NotFound
from restapi.models import Schema, fields, validate
from restapi.rest.definition import Response
from restapi.services.authentication import User

# from restapi.utilities.logs import log
DATE_FORMAT = "%Y-%m-%d"

# NOTE: the platform -> compatible kits association below is permissive (every
# kit is currently allowed on every platform) pending confirmation from the lab
# domain referent (see issues #49/#52). The data structure and validation are
# final; only the association itself may be narrowed later.
PLATFORM_KITS: Dict[str, List[str]] = {
    "Illumina": [
        "Illumina Nextera Rapid Capture V.1.2",
        "Agilent SureSelectXT AllExon V.5",
        "Agilent SureSelect Clinical Research Exome v2",
        "Agilent SureSelect AllExon_v7",
        "Twist Human Core Exome",
        "KAPA HyperExome hg38 primary targets v2 slop50",
    ],
    "Ion": [
        "Illumina Nextera Rapid Capture V.1.2",
        "Agilent SureSelectXT AllExon V.5",
        "Agilent SureSelect Clinical Research Exome v2",
        "Agilent SureSelect AllExon_v7",
        "Twist Human Core Exome",
        "KAPA HyperExome hg38 primary targets v2 slop50",
    ],
    "Pacific Biosciences": [
        "Illumina Nextera Rapid Capture V.1.2",
        "Agilent SureSelectXT AllExon V.5",
        "Agilent SureSelect Clinical Research Exome v2",
        "Agilent SureSelect AllExon_v7",
        "Twist Human Core Exome",
        "KAPA HyperExome hg38 primary targets v2 slop50",
    ],
}
PLATFORMS = list(PLATFORM_KITS.keys())
ENRICHMENT_KITS = sorted({kit for kits in PLATFORM_KITS.values() for kit in kits})


class _TechmetaBaseSchema(Schema):
    @pre_load
    def null_platform(self, data: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        if "platform" in data and data["platform"] == "":
            data["platform"] = None
        return data

    @validates_schema
    def validate_platform_kit(self, data: Dict[str, Any], **kwargs: Any) -> None:
        platform = data.get("platform")
        kit = data.get("enrichment_kit")
        if platform and kit and kit not in PLATFORM_KITS.get(platform, []):
            raise ValidationError(
                f"Enrichment kit '{kit}' is not compatible with platform '{platform}'",
                field_name="enrichment_kit",
            )


def _resolve_study_for_techmeta(request: FlaskRequest, is_post: bool) -> Any:
    # Only used to decide whether enrichment_kit applies (genome studies do not
    # require it, issue #61); actual access control still happens in the view.
    if not request:
        return None
    graph = neo4j.get_instance()
    if is_post:
        study_uuid = request.view_args["uuid"]
        return graph.Study.nodes.get_or_none(uuid=study_uuid)
    techmeta_uuid = request.view_args["uuid"]
    techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=techmeta_uuid)
    return techmeta.defined_in.single() if techmeta else None


def getTechmetaInputSchema(request: FlaskRequest, is_post: bool) -> Type[Schema]:
    attributes: Dict[str, Union[fields.Field, type]] = {}
    attributes["name"] = fields.Str(required=is_post)
    attributes["sequencing_date"] = fields.Date(format=DATE_FORMAT)
    attributes["platform"] = fields.Str(
        required=is_post, allow_none=not is_post, validate=validate.OneOf(PLATFORMS)
    )

    study = _resolve_study_for_techmeta(request, is_post)
    # enrichment_kit is required for exome studies (default when the parent study
    # is not resolvable yet, e.g. during OpenAPI spec generation) and omitted
    # entirely for genome studies, so it neither renders in the form nor is
    # accepted as input for them.
    if study is None or study.study_type != "genome":
        attributes["enrichment_kit"] = fields.Str(
            required=is_post,
            allow_none=not is_post,
            validate=validate.OneOf(ENRICHMENT_KITS),
        )

    return _TechmetaBaseSchema.from_dict(
        attributes, name="TechnicalMetadataDefinition"
    )


def getTechmetaPOSTInputSchema(request: FlaskRequest) -> Type[Schema]:
    return getTechmetaInputSchema(request, True)


def getTechmetaPUTInputSchema(request: FlaskRequest) -> Type[Schema]:
    return getTechmetaInputSchema(request, False)


class TechmetaOutputSchema(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    sequencing_date = fields.Date(format=DATE_FORMAT)
    platform = fields.Str()
    enrichment_kit = fields.Str()


class TechnicalOptionsOutput(Schema):
    platforms = fields.List(fields.Str())
    platform_kits = fields.Dict(keys=fields.Str(), values=fields.List(fields.Str()))


class TechnicalOptions(NIGEndpoint):

    labels = ["technicals"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/technicals/options",
        summary="Get the allowed platform/enrichment kit combinations",
        responses={
            200: "Options successfully retrieved",
        },
    )
    @decorators.marshal_with(TechnicalOptionsOutput, code=200)
    def get(self, user: User) -> Response:
        return self.response(
            {"platforms": PLATFORMS, "platform_kits": PLATFORM_KITS}
        )


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
    def get(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, user=user, read=True)
        nodeset = study.technicals

        data = []
        for techmeta in nodeset.all():

            data.append(techmeta)

        return self.response(data)


class TechnicalMetadata(NIGEndpoint):

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
    def get(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=uuid)
        if not techmeta:
            raise NotFound(TECHMETA_NOT_FOUND)
        study = techmeta.defined_in.single()
        self.verifyStudyAccess(
            study, user=user, error_type="Technical Metadata", read=True
        )

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
    @decorators.use_kwargs(getTechmetaPOSTInputSchema)
    def post(self, uuid: str, user: User, **kwargs: Any) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, user=user)

        # defensive: the dynamic schema already omits enrichment_kit for genome
        # studies, this only guards against a caller that bypassed schema
        # generation (e.g. a stale client-side form)
        if study.study_type == "genome":
            kwargs.pop("enrichment_kit", None)

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
    @decorators.use_kwargs(getTechmetaPUTInputSchema)
    def put(self, uuid: str, user: User, **kwargs: Any) -> Response:

        graph = neo4j.get_instance()

        techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=uuid)
        if techmeta is None:
            raise NotFound(TECHMETA_NOT_FOUND)
        study = techmeta.defined_in.single()
        self.verifyStudyAccess(study, user=user, error_type="Technical Metadata")

        # defensive: the dynamic schema already omits enrichment_kit for genome
        # studies, this only guards against a caller that bypassed schema
        # generation (e.g. a stale client-side form)
        if study.study_type == "genome":
            kwargs.pop("enrichment_kit", None)

        # a partial update (only platform or only enrichment_kit) cannot be
        # validated by the schema alone, which only sees the submitted fields:
        # fall back to the persisted value for whichever field is not being
        # changed in this request
        effective_platform = kwargs.get("platform", techmeta.platform)
        effective_kit = kwargs.get("enrichment_kit", techmeta.enrichment_kit)
        if (
            effective_platform
            and effective_kit
            and effective_kit not in PLATFORM_KITS.get(effective_platform, [])
        ):
            raise BadRequest(
                f"Enrichment kit '{effective_kit}' is not compatible with "
                f"platform '{effective_platform}'"
            )

        graph.update_properties(techmeta, kwargs)
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
    def delete(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        techmeta = graph.TechnicalMetadata.nodes.get_or_none(uuid=uuid)
        if techmeta is None:
            raise NotFound(TECHMETA_NOT_FOUND)
        study = techmeta.defined_in.single()
        self.verifyStudyAccess(study, user=user, error_type="Technical Metadata")

        techmeta.delete()

        self.log_event(self.events.delete, techmeta)

        return self.empty_response()
