from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
from nig.endpoints import PHENOTYPE_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import NotFound
from restapi.models import ISO8601UTC, Schema, fields, validate
from restapi.rest.definition import Response

# from restapi.connectors import celery

# from restapi.utilities.logs import log
SEX = ["male", "female"]


class Hpo(Schema):
    uuid = fields.Str(required=True)
    label = fields.Str(required=True)


class PhenotypeOutputSchema(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    birthday = fields.DateTime(format=ISO8601UTC)
    deathday = fields.DateTime(format=ISO8601UTC)
    sex = fields.Str(required=True, validate=validate.OneOf(SEX))
    hpo = fields.List(fields.Nested(Hpo), required=False)


class PhenotypeInputSchema(Schema):
    name = fields.Str(required=True)
    birthday = fields.DateTime(format=ISO8601UTC)
    deathday = fields.DateTime(format=ISO8601UTC)
    sex = fields.Str(required=True, validate=validate.OneOf(SEX))
    birth_place_uuids = fields.List(fields.Str())
    hpo_uuids = fields.List(fields.Str())


class PhenotypePutSchema(Schema):
    name = fields.Str(required=False)
    birthday = fields.DateTime(format=ISO8601UTC)
    deathday = fields.DateTime(format=ISO8601UTC)
    sex = fields.Str(required=False, validate=validate.OneOf(SEX))
    birth_place_uuids = fields.List(fields.Str())
    hpo_uuids = fields.List(fields.Str())


class Phenotypes(NIGEndpoint):

    # schema_expose = True
    labels = ["phenotype"]

    def link_hpo(self, graph, phenotype, hpo_uuids):
        for p in phenotype.hpo.all():
            phenotype.hpo.disconnect(p)
        connected_hpo = []
        for uuid in hpo_uuids:
            hpo = graph.HPO.nodes.get_or_none(uuid=uuid)
            if hpo:
                phenotype.hpo.connect(hpo)
                connected_hpo.append(uuid)
        return connected_hpo

    def link_geodata(self, graph, phenotype, geodata_uuids):
        for p in phenotype.birth_place.all():
            phenotype.birth_place.disconnect(p)

        connected_geo = []
        for uuid in geodata_uuids:
            geo = graph.GeoData.nodes.get_or_none(uuid=uuid)
            if geo:
                phenotype.birth_place.connect(geo)
                connected_geo.append(uuid)
        return connected_geo

    def check_timezone(self, date):
        if date.tzinfo is None:
            date = pytz.utc.localize(date)
        return date

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<study_uuid>/phenotypes",
        summary="Obtain the list of phenotypes in a study",
        responses={
            200: "Phenotype information successfully retrieved",
            404: "This study cannot be found or you are not authorized to access",
        },
    )
    @decorators.endpoint(
        path="/phenotype/<phenotype_uuid>",
        summary="Obtain information on a single phenotype",
        responses={
            200: "Phenotype information successfully retrieved",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    @decorators.marshal_with(PhenotypeOutputSchema(many=True), code=200)
    def get(
        self, study_uuid: Optional[str] = None, phenotype_uuid: Optional[str] = None
    ) -> Response:

        graph = neo4j.get_instance()

        if phenotype_uuid is not None:
            phenotype = graph.Phenotype.nodes.get_or_none(uuid=phenotype_uuid)
            if phenotype is None:
                raise NotFound(PHENOTYPE_NOT_FOUND)
            study = phenotype.defined_in.single()
            self.verifyStudyAccess(study, error_type="Phenotype", read=True)
            nodeset = graph.Phenotype.nodes.filter(uuid=phenotype_uuid)

        elif study_uuid is not None:
            study = graph.Study.nodes.get_or_none(uuid=study_uuid)
            self.verifyStudyAccess(study, read=True)
            nodeset = study.phenotypes

        data = []
        for t in nodeset.all():

            phenotype_el = {
                "uuid": t.uuid,
                "name": t.name,
                "birthday": t.birthday,
                "deathday": t.deathday,
                "sex": t.sex,
            }
            hpo_nodeset = t.hpo.all()
            phenotype_el["hpo"] = []
            if hpo_nodeset:
                for h in hpo_nodeset:
                    hh = graph.HPO.nodes.get_or_none(uuid=h.uuid)
                    for hhh in hh.generalized_parent.all():
                        if hhh.hide_node:
                            continue
                        hpo_el = {"uuid": hhh.uuid, "label": hhh.label}
                        phenotype_el["hpo"].append(hpo_el)

            data.append(phenotype_el)

        if phenotype_uuid is not None:
            self.log_event(self.events.access, phenotype)

        return self.response(data)

    @decorators.auth.require()
    # {'custom_parameters': ['Phenotype']}
    @decorators.endpoint(
        path="/study/<uuid>/phenotypes",
        summary="Create a new phenotype in a study",
        responses={
            200: "The uuid of the new phenotype",
            404: "This study cannot be found or you are not authorized to access",
        },
    )
    @decorators.graph_transactions
    @decorators.use_kwargs(PhenotypeInputSchema)
    def post(
        self,
        uuid: str,
        name: str,
        sex: str,
        birthday: Optional[datetime] = None,
        deathday: Optional[datetime] = None,
        birth_place_uuids: Optional[List[str]] = [],
        hpo_uuids: Optional[List[str]] = [],
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
        if birth_place_uuids:
            connected_geodata = self.link_geodata(graph, phenotype, birth_place_uuids)
            kwargs["birth_place"] = connected_geodata
        if hpo_uuids:
            connected_hpo = self.link_hpo(graph, phenotype, hpo_uuids)
            kwargs["hpo"] = connected_hpo

        # c = celery.get_instance()
        # c.celery_app.send_task(
        #     "link_variants", args=[phenotype.uuid], countdown=5
        # )
        self.log_event(self.events.create, phenotype, kwargs)

        return self.response(phenotype.uuid)

    @decorators.auth.require()
    # {'custom_parameters': ['Phenotype']}
    @decorators.endpoint(
        path="/phenotype/<uuid>",
        summary="Modify a phenotype",
        responses={
            200: "Phenotype successfully modified",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    @decorators.graph_transactions
    @decorators.use_kwargs(PhenotypePutSchema)
    def put(
        self,
        uuid: str,
        name: Optional[str] = None,
        sex: Optional[str] = None,
        birthday: Optional[datetime] = None,
        deathday: Optional[datetime] = None,
        birth_place_uuids: Optional[List[str]] = [],
        hpo_uuids: Optional[List[str]] = [],
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
        if birth_place_uuids:
            connected_geodata = self.link_geodata(graph, phenotype, birth_place_uuids)
            kwargs["birth_place"] = connected_geodata
        if hpo_uuids:
            connected_hpo = self.link_hpo(graph, phenotype, hpo_uuids)
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
    @decorators.graph_transactions
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
