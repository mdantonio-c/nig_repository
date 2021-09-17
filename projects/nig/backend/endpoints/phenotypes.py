from datetime import datetime
from typing import Any, Dict, List, Optional, Type, Union

import pytz
from nig.endpoints import PHENOTYPE_NOT_FOUND, NIGEndpoint
from nig.endpoints._injectors import verify_phenotype_access, verify_study_access
from restapi import decorators
from restapi.connectors import neo4j
from restapi.customizer import FlaskRequest
from restapi.exceptions import NotFound
from restapi.models import Schema, fields, validate
from restapi.rest.definition import Response
from restapi.services.authentication import User

# from restapi.connectors import celery
# from restapi.utilities.logs import log

SEX = ["male", "female"]


class Hpo(Schema):
    hpo_id = fields.Str(required=True)
    label = fields.Str(required=True)


class GeoData(Schema):
    uuid = fields.Str(required=True)
    country = fields.Str(required=True)
    region = fields.Str(required=True)
    province = fields.Str(required=True)
    code = fields.Str(required=True)


class FamilyMembers(Schema):
    uuid = fields.Str(required=False)
    name = fields.Str(required=False)


class Relationships(Schema):
    mother = fields.Nested(FamilyMembers, required=False)
    father = fields.Nested(FamilyMembers, required=False)
    sons = fields.List(fields.Nested(FamilyMembers, required=False), required=False)


class PhenotypeOutputSchema(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    age = fields.Integer()
    sex = fields.Str(required=True, validate=validate.OneOf(SEX))
    hpo = fields.List(fields.Nested(Hpo), required=False)
    birth_place = fields.Nested(GeoData, required=False)
    relationships = fields.Nested(
        Relationships,
        metadata={"description": "family relationships between phenotypes"},
    )


def getInputSchema(request: FlaskRequest, is_post: bool) -> Type[Schema]:
    graph = neo4j.get_instance()
    # as defined in Marshmallow.schema.from_dict
    attributes: Dict[str, Union[fields.Field, type]] = {}

    attributes["name"] = fields.Str(required=True)
    attributes["age"] = fields.Integer(allow_none=True)
    attributes["sex"] = fields.Str(
        required=True, validate=validate.OneOf(SEX), metadata={"description": ""}
    )
    attributes["hpo"] = fields.List(
        fields.Str(),
        metadata={
            "label": "HPO",
            "autocomplete_endpoint": "/api/hpo",
            "autocomplete_show_id": True,
            "autocomplete_id_bind": "hpo_id",
            "autocomplete_label_bind": "label",
        },
    )

    geodata_keys = []
    geodata_labels = []

    for g in graph.GeoData.nodes.all():
        geodata_keys.append(g.uuid)
        geodata_labels.append(g.province)

    if len(geodata_keys) == 1:
        default_geodata = geodata_keys[0]
    else:
        default_geodata = None

    attributes["birth_place"] = fields.Str(
        required=False,
        allow_none=True,
        metadata={
            "label": "Birth Place",
            "description": "",
        },
        dump_default=default_geodata,
        validate=validate.OneOf(choices=geodata_keys, labels=geodata_labels),
    )

    return Schema.from_dict(attributes, name="PhenotypeDefinition")


def getPOSTInputSchema(request: FlaskRequest) -> Type[Schema]:
    return getInputSchema(request, True)


def getPUTInputSchema(request: FlaskRequest) -> Type[Schema]:
    return getInputSchema(request, False)


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
    def get(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, user=user, read=True)
        nodeset = study.phenotypes

        data = []
        for phenotype in nodeset.all():
            phenotype_el = {}
            phenotype_el["uuid"] = phenotype.uuid
            phenotype_el["name"] = phenotype.name
            if phenotype.age:
                phenotype_el["age"] = phenotype.age
            phenotype_el["sex"] = phenotype.sex
            phenotype_el["hpo"] = []
            for hpo in phenotype.hpo:
                hpo_el = {}
                hpo_el["hpo_id"] = hpo.hpo_id
                hpo_el["label"] = hpo.label
                phenotype_el["hpo"].append(hpo_el)

            if phenotype.birth_place.single():
                phenotype_el["birth_place"] = {}
                phenotype_el["birth_place"][
                    "uuid"
                ] = phenotype.birth_place.single().uuid
                phenotype_el["birth_place"][
                    "country"
                ] = phenotype.birth_place.single().country
                phenotype_el["birth_place"][
                    "region"
                ] = phenotype.birth_place.single().region
                phenotype_el["birth_place"][
                    "province"
                ] = phenotype.birth_place.single().province
                phenotype_el["birth_place"][
                    "code"
                ] = phenotype.birth_place.single().code

            phenotype_el["relationships"] = {}
            if phenotype.father:
                phenotype_el["relationships"]["father"] = {}
                phenotype_el["relationships"]["father"][
                    "uuid"
                ] = phenotype.father.single().uuid
                phenotype_el["relationships"]["father"][
                    "name"
                ] = phenotype.father.single().name
            if phenotype.mother:
                phenotype_el["relationships"]["mother"] = {}
                phenotype_el["relationships"]["mother"][
                    "uuid"
                ] = phenotype.mother.single().uuid
                phenotype_el["relationships"]["mother"][
                    "name"
                ] = phenotype.mother.single().name
            if phenotype.son:
                phenotype_el["relationships"]["sons"] = []
                for son in phenotype.son.all():
                    son_el = {}
                    son_el["uuid"] = son.uuid
                    son_el["name"] = son.name
                    phenotype_el["relationships"]["sons"].append(son_el)
            data.append(phenotype_el)

        return self.response(data)


class Phenotypes(NIGEndpoint):

    # schema_expose = True
    labels = ["phenotype"]

    def link_hpo(
        self, graph: neo4j.NeoModel, phenotype: Any, hpo: List[str]
    ) -> List[str]:
        # disconnect all previous hpo
        for p in phenotype.hpo.all():
            phenotype.hpo.disconnect(p)

        connected_hpo = []
        for id in hpo:
            hpo = graph.HPO.nodes.get_or_none(hpo_id=id)
            if hpo:
                phenotype.hpo.connect(hpo)
                connected_hpo.append(id)
        return connected_hpo

    def link_geodata(
        self, graph: neo4j.NeoModel, phenotype: Any, geodata_uuid: str
    ) -> None:
        if previous := phenotype.birth_place.single():
            phenotype.birth_place.disconnect(previous)

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
    def get(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        phenotype = graph.Phenotype.nodes.get_or_none(uuid=uuid)
        if not phenotype:
            raise NotFound(PHENOTYPE_NOT_FOUND)
        study = phenotype.defined_in.single()
        self.verifyStudyAccess(study, user=user, error_type="Phenotype", read=True)

        self.log_event(self.events.access, phenotype)

        phenotype_el = {}
        phenotype_el["uuid"] = phenotype.uuid
        phenotype_el["name"] = phenotype.name
        if phenotype.age:
            phenotype_el["age"] = phenotype.age
        phenotype_el["sex"] = phenotype.sex
        phenotype_el["hpo"] = []
        for hpo in phenotype.hpo:
            hpo_el = {}
            hpo_el["hpo_id"] = hpo.hpo_id
            hpo_el["label"] = hpo.label
            phenotype_el["hpo"].append(hpo_el)

        if phenotype.birth_place.single():
            phenotype_el["birth_place"] = {}
            phenotype_el["birth_place"]["uuid"] = phenotype.birth_place.single().uuid
            phenotype_el["birth_place"][
                "country"
            ] = phenotype.birth_place.single().country
            phenotype_el["birth_place"][
                "region"
            ] = phenotype.birth_place.single().region
            phenotype_el["birth_place"][
                "province"
            ] = phenotype.birth_place.single().province
            phenotype_el["birth_place"]["code"] = phenotype.birth_place.single().code

        phenotype_el["relationships"] = {}
        if phenotype.father:
            phenotype_el["relationships"]["father"] = {}
            phenotype_el["relationships"]["father"][
                "uuid"
            ] = phenotype.father.single().uuid
            phenotype_el["relationships"]["father"][
                "name"
            ] = phenotype.father.single().name
        if phenotype.mother:
            phenotype_el["relationships"]["mother"] = {}
            phenotype_el["relationships"]["mother"][
                "uuid"
            ] = phenotype.mother.single().uuid
            phenotype_el["relationships"]["mother"][
                "name"
            ] = phenotype.mother.single().name
        if phenotype.son:
            phenotype_el["relationships"]["sons"] = []
            for son in phenotype.son.all():
                son_el = {}
                son_el["uuid"] = son.uuid
                son_el["name"] = son.name
                phenotype_el["relationships"]["sons"].append(son_el)

        return self.response(phenotype_el)

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
    @decorators.preload(callback=verify_study_access)
    @decorators.use_kwargs(getPOSTInputSchema)
    def post(
        self,
        uuid: str,
        name: str,
        sex: str,
        # should be an instance of neo4j.Study,
        # but typing is still not working with neomodel
        study: Any,
        user: User,
        age: Optional[int] = None,
        birth_place: Optional[str] = None,
        hpo: Optional[List[str]] = None,
    ) -> Response:

        graph = neo4j.get_instance()

        kwargs: Dict[str, Optional[Any]] = {}
        if age:
            kwargs["age"] = age

        kwargs["name"] = name
        kwargs["sex"] = sex

        phenotype = graph.Phenotype(**kwargs).save()

        phenotype.defined_in.connect(study)
        if birth_place:
            self.link_geodata(graph, phenotype, birth_place)
            kwargs["birth_place"] = birth_place
        if hpo:
            connected_hpo = self.link_hpo(graph, phenotype, hpo)
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
    @decorators.preload(callback=verify_phenotype_access)
    @decorators.use_kwargs(getPUTInputSchema)
    def put(
        self,
        uuid: str,
        name: str,
        sex: str,
        # should be an instance of neo4j.Phenotype,
        # but typing is still not working with neomodel
        phenotype: Any,
        # should be an instance of neo4j.Study,
        # but typing is still not working with neomodel
        study: Any,
        user: User,
        age: Optional[int] = None,
        birth_place: Optional[str] = None,
        hpo: Optional[List[str]] = None,
    ) -> Response:

        graph = neo4j.get_instance()

        kwargs: Dict[str, Optional[Any]] = {}

        if age:
            phenotype.age = age
            kwargs["age"] = age

        phenotype.name = name
        kwargs["name"] = name

        phenotype.sex = sex
        kwargs["sex"] = sex

        if birth_place:
            self.link_geodata(graph, phenotype, birth_place)
            kwargs["birth_place"] = birth_place
        else:
            # check if there is a birth place and if yes disconnect the node
            if previous := phenotype.birth_place.single():
                phenotype.birth_place.disconnect(previous)

        if hpo:
            connected_hpo = self.link_hpo(graph, phenotype, hpo)
            kwargs["hpo"] = connected_hpo
        else:
            # disconnect all hpo if any
            for p in phenotype.hpo.all():
                phenotype.hpo.disconnect(p)

        phenotype.save()

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
    def delete(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        phenotype = graph.Phenotype.nodes.get_or_none(uuid=uuid)
        if phenotype is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)
        study = phenotype.defined_in.single()
        self.verifyStudyAccess(study, user=user, error_type="Phenotype")

        phenotype.delete()

        self.log_event(self.events.delete, phenotype)

        return self.empty_response()
