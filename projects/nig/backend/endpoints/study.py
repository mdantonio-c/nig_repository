import os
import shutil
from typing import Any

from nig.endpoints import NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import Conflict
from restapi.models import Neo4jRelationshipToCount, Schema, fields
from restapi.rest.definition import Response

# from restapi.utilities.logs import log


# Output schema
class StudyOutput(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    description = fields.Str(required=True)
    # Number of related datasets
    datasets = Neo4jRelationshipToCount()
    phenotypes = Neo4jRelationshipToCount()
    technicals = Neo4jRelationshipToCount()


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
    def get(self) -> Response:

        graph = neo4j.get_instance()

        data = []
        for t in graph.Study.nodes.order_by().all():

            if not self.verifyStudyAccess(t, read=True, raiseError=False):
                continue

            data.append(t)

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
    def get(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, read=True)

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
    @decorators.graph_transactions
    def post(self, **kwargs: Any) -> Response:

        graph = neo4j.get_instance()

        current_user = self.get_user()

        study = graph.Study(**kwargs).save()

        study.ownership.connect(current_user)

        path = self.getPath(study=study)

        try:
            os.makedirs(path, exist_ok=False)
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
    @decorators.graph_transactions
    def put(self, uuid: str, **kwargs: Any) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study)

        self.auth.db.update_properties(study, kwargs)
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
    @decorators.graph_transactions
    def delete(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study)

        path = self.getPath(study=study)

        for d in study.datasets.all():
            for f in d.files.all():
                f.delete()
            d.delete()

        for n in study.phenotypes.all():
            n.delete()

        for n in study.technicals.all():
            n.delete()

        for n in study.resources.all():
            for v in n.virtual_file.all():
                v.delete()
            n.delete()

        study.delete()

        # remove the study folder
        shutil.rmtree(path)

        self.log_event(self.events.delete, study)

        return self.empty_response()
