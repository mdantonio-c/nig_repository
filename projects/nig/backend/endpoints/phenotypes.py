from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
from nig.endpoints import PHENOTYPE_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import NotFound
from restapi.models import (
    ISO8601UTC,
    Neo4jRelationshipToMany,
    Neo4jRelationshipToSingle,
    Schema,
    fields,
    validate,
)
from restapi.rest.definition import Response

# from restapi.connectors import celery

# from restapi.utilities.logs import log
SEX = ["male", "female"]


class Hpo(Schema):
    hpo_id = fields.Str(required=True)
    label = fields.Str(required=True)


class GeoData(Schema):
    country = fields.Str(required=True)
    region = fields.Str(required=True)
    province = fields.Str(required=True)
    code = fields.Str(required=True)


class PhenotypeOutputSchema(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    birthday = fields.DateTime(format=ISO8601UTC)
    deathday = fields.DateTime(format=ISO8601UTC)
    sex = fields.Str(required=True, validate=validate.OneOf(SEX))
    hpo = Neo4jRelationshipToMany(Hpo)
    birth_place = Neo4jRelationshipToSingle(GeoData)


class PhenotypeInputSchema(Schema):
    name = fields.Str(required=True)
    birthday = fields.DateTime(format=ISO8601UTC)
    deathday = fields.DateTime(format=ISO8601UTC)
    sex = fields.Str(required=True, validate=validate.OneOf(SEX))
    birth_place_uuid = fields.Str()
    hpo_ids = fields.List(fields.Str())


class PhenotypePutSchema(Schema):
    name = fields.Str(required=False)
    birthday = fields.DateTime(format=ISO8601UTC)
    deathday = fields.DateTime(format=ISO8601UTC)
    sex = fields.Str(required=False, validate=validate.OneOf(SEX))
    birth_place_uuids = fields.List(fields.Str())
    hpo_ids = fields.List(fields.Str())


class PhenotypeList(NIGEndpoint):

    # schema_expose = True
    labels = ["phenotype"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<uuid>/phenotypes",
        summary="Obtain the list of phenotypes in a study",
        responses={
            200: "Phenotype information successfully retrieved",
            404: "This study cannot be found or you are not authorized to access",
        },
    )
    @decorators.marshal_with(PhenotypeOutputSchema(many=True), code=200)
    def get(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, read=True)
        nodeset = study.phenotypes

        data = []
        for phenotype in nodeset.all():

            data.append(phenotype)

        return self.response(data)


class Phenotypes(NIGEndpoint):

    # schema_expose = True
    labels = ["phenotype"]

    def link_hpo(
        self, graph: neo4j.Neomodel, phenotype: Any, hpo_ids: List[str]
    ) -> List[str]:
        # if the hpo list is empty it means "disconnect all phenotypes"
        for p in phenotype.hpo.all():
            phenotype.hpo.disconnect(p)
        connected_hpo = []
        for id in hpo_ids:
            hpo = graph.HPO.nodes.get_or_none(hpo_id=id)
            if hpo:
                phenotype.hpo.connect(hpo)
                connected_hpo.append(id)
        return connected_hpo

    def link_geodata(
        self, graph: neo4j.Neomodel, phenotype: Any, geodata_uuid: List[str]
    ) -> List[str]:
        if previous := phenotype.birth_place.single():
            phenotype.birth_place.disconnect(previous)

        if geodata_uuid != "-1":
            geodata = graph.GeoData.nodes.get_or_none(uuid=geodata_uuid)
            if geodata is None:
                raise NotFound("This birth place cannot be found")

            phenotype.birth_place.connect(geodata)

    def check_timezone(self, date: datetime) -> datetime:
        if date.tzinfo is None:
            date = pytz.utc.localize(date)
        return date

    @decorators.auth.require()
    @decorators.endpoint(
        path="/phenotype/<uuid>",
        summary="Obtain information on a single phenotype",
        responses={
            200: "Phenotype information successfully retrieved",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    @decorators.marshal_with(PhenotypeOutputSchema, code=200)
    def get(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        phenotype = graph.Phenotype.nodes.get_or_none(uuid=uuid)
        if not phenotype:
            raise NotFound(PHENOTYPE_NOT_FOUND)
        study = phenotype.defined_in.single()
        self.verifyStudyAccess(study, error_type="Phenotype", read=True)

        self.log_event(self.events.access, phenotype)

        return self.response(phenotype)

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<uuid>/phenotypes",
        summary="Create a new phenotype in a study",
        responses={
            200: "The uuid of the new phenotype",
            404: "This study cannot be found or you are not authorized to access",
        },
    )
    @decorators.database_transaction
    @decorators.use_kwargs(PhenotypeInputSchema)
    def post(
        self,
        uuid: str,
        name: str,
        sex: str,
        birthday: Optional[datetime] = None,
        deathday: Optional[datetime] = None,
        birth_place_uuid: Optional[str] = None,
        hpo_ids: Optional[List[str]] = None,
    ) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study)

        kwargs: Dict[str, Optional[Any]] = {}
        if birthday:
            birthday = self.check_timezone(birthday)
            kwargs["birthday"] = birthday

        if deathday:
            deathday = self.check_timezone(deathday)
            kwargs["deathday"] = deathday

        if name:
            kwargs["name"] = name
        if sex:
            kwargs["sex"] = sex

        phenotype = graph.Phenotype(**kwargs).save()

        phenotype.defined_in.connect(study)
        if birth_place_uuid:
            self.link_geodata(graph, phenotype, birth_place_uuid)
            kwargs["birth_place"] = birth_place_uuid
        if hpo_ids:
            connected_hpo = self.link_hpo(graph, phenotype, hpo_ids)
            kwargs["hpo"] = connected_hpo

        # c = celery.get_instance()
        # c.celery_app.send_task(
        #     "link_variants", args=[phenotype.uuid], countdown=5
        # )
        self.log_event(self.events.create, phenotype, kwargs)

        return self.response(phenotype.uuid)

    @decorators.auth.require()
    @decorators.endpoint(
        path="/phenotype/<uuid>",
        summary="Modify a phenotype",
        responses={
            200: "Phenotype successfully modified",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    @decorators.database_transaction
    @decorators.use_kwargs(PhenotypePutSchema)
    def put(
        self,
        uuid: str,
        name: Optional[str] = None,
        sex: Optional[str] = None,
        birthday: Optional[datetime] = None,
        deathday: Optional[datetime] = None,
        birth_place_uuid: Optional[str] = None,
        hpo_ids: Optional[List[str]] = None,
    ) -> Response:

        graph = neo4j.get_instance()

        phenotype = graph.Phenotype.nodes.get_or_none(uuid=uuid)
        if phenotype is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)
        study = phenotype.defined_in.single()
        self.verifyStudyAccess(study, error_type="Phenotype")
        kwargs: Dict[str, Optional[Any]] = {}
        if birthday:
            birthday = self.check_timezone(birthday)
            phenotype.birthday = birthday
            kwargs["birthday"] = birthday

        if deathday:
            deathday = self.check_timezone(deathday)
            phenotype.deathday = deathday
            kwargs["deathday"] = deathday

        if name:
            phenotype.name = name
            kwargs["name"] = name
        if sex:
            phenotype.sex = sex
            kwargs["sex"] = sex

        phenotype.save()
        if birth_place_uuid:
            self.link_geodata(graph, phenotype, birth_place_uuid)
            kwargs["birth_place"] = birth_place_uuid
        if hpo_ids:
            connected_hpo = self.link_hpo(graph, phenotype, hpo_ids)
            kwargs["hpo"] = connected_hpo

        # c = celery.get_instance()
        # c.celery_app.send_task(
        #     "link_variants", args=[phenotype.uuid], countdown=5
        # )

        self.log_event(self.events.modify, study, kwargs)

        return self.empty_response()

    @decorators.auth.require()
    @decorators.endpoint(
        path="/phenotype/<uuid>",
        summary="Delete a phenotype",
        responses={
            200: "Phenotype successfully deleted",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    @decorators.database_transaction
    def delete(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        phenotype = graph.Phenotype.nodes.get_or_none(uuid=uuid)
        if phenotype is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)
        study = phenotype.defined_in.single()
        self.verifyStudyAccess(study, error_type="Phenotype")

        phenotype.delete()

        self.log_event(self.events.delete, phenotype)

        return self.empty_response()
