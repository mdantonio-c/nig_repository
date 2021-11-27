import shutil
from typing import Any

from marshmallow import post_dump
from nig.endpoints import NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import Conflict
from restapi.models import Schema, fields
from restapi.rest.definition import Response
from restapi.services.authentication import User

# from restapi.utilities.logs import log


# Output schema
class StudyOutput(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    description = fields.Str(required=True)
    # Number of related datasets
    datasets = fields.Neo4jRelationshipToCount()
    phenotypes = fields.Neo4jRelationshipToCount()
    technicals = fields.Neo4jRelationshipToCount()
    readonly = fields.Bool(default=True)
    owning_group_name = fields.Str()


class StudyInputSchema(Schema):
    name = fields.Str(required=True)
    description = fields.Str(required=True)


class StudyPutSchema(Schema):
    name = fields.Str(required=False)
    description = fields.Str(required=False)


class Studies(NIGEndpoint):
    labels = ["study"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study",
        summary="List of studies to which you have access",
        responses={
            200: "List of studies successfully retrieved",
        },
    )
    @decorators.marshal_with(StudyOutput(many=True), code=200)
    def get(self, user: User) -> Response:

        graph = neo4j.get_instance()

        data = []
        for t in graph.Study.nodes.order_by().all():

            if not self.verifyStudyAccess(t, user=user, read=True, raiseError=False):
                continue

            study_el = {}
            study_el["uuid"] = t.uuid
            study_el["name"] = t.name
            study_el["description"] = t.description
            study_el["datasets"] = t.datasets
            study_el["phenotypes"] = t.phenotypes
            study_el["technicals"] = t.technicals
            owner = t.ownership.single()
            if owner == user:
                study_el["readonly"] = False

            for group in owner.belongs_to.all():
                study_el["owning_group_name"] = group.fullname
                if group.members.is_connected(user):
                    study_el["readonly"] = False

            data.append(study_el)

        return self.response(data)


class Study(NIGEndpoint):

    labels = ["study"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<uuid>",
        summary="Get a single study",
        responses={
            200: "study successfully retrieved",
            404: "This study cannot be found or you are not authorized to access",
        },
    )
    @decorators.marshal_with(StudyOutput, code=200)
    def get(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, user=user, read=True)

        self.log_event(self.events.access, study)

        return self.response(study)

    @decorators.auth.require()
    @decorators.use_kwargs(StudyInputSchema)
    @decorators.endpoint(
        path="/study",
        summary="Create a new study",
        responses={
            200: "Study successfully created. the new uuid is returned",
        },
    )
    @decorators.database_transaction
    def post(self, user: User, **kwargs: Any) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study(**kwargs).save()

        study.ownership.connect(user)

        path = self.getPath(user=user, study=study)

        try:
            path.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:  # pragma: no cover
            # Almost impossible the have same uuid was already used for an other study
            study.delete()
            raise Conflict(str(exc))

        self.log_event(self.events.create, study, kwargs)

        return self.response(study.uuid)

    @decorators.auth.require()
    @decorators.use_kwargs(StudyPutSchema)
    @decorators.endpoint(
        path="/study/<uuid>",
        summary="Modify a study",
        responses={
            200: "Study successfully modified",
            404: "This study cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this study",
        },
    )
    @decorators.database_transaction
    def put(self, uuid: str, user: User, **kwargs: Any) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, user=user)

        graph.update_properties(study, kwargs)
        study.save()

        self.log_event(self.events.modify, study, kwargs)

        return self.empty_response()

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<uuid>",
        summary="Delete a study",
        responses={
            200: "Study successfully deleted",
            404: "This study cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this study",
        },
    )
    @decorators.database_transaction
    def delete(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, user=user)

        input_path = self.getPath(user=user, study=study)
        output_path = self.getPath(user=user, study=study, get_output_dir=True)

        for d in study.datasets.all():
            for f in d.files.all():
                f.delete()
            d.delete()

        for n in study.phenotypes.all():
            n.delete()

        for n in study.technicals.all():
            n.delete()

        study.delete()

        # remove the study folders
        shutil.rmtree(input_path)
        # if there is an output dir, delete it
        if output_path.is_dir():
            shutil.rmtree(output_path)

        self.log_event(self.events.delete, study)

        return self.empty_response()
