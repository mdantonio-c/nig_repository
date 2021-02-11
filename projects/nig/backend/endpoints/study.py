import os
import shutil
from typing import Any, Optional

from nig.endpoints import STUDY_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import Conflict, NotFound
from restapi.models import Schema, fields
from restapi.rest.definition import Response
from restapi.utilities.logs import log


# Output schema
class StudyOutput(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    description = fields.Str(required=True)
    datasets = (
        fields.Int()
    )  # for now only the number of related datasets, can be useful also a list of datasets metadata?
    # the motivation of access can be useful??


class StudyInputSchema(Schema):
    name = fields.Str(required=True)
    description = fields.Str(required=True)


class StudyPutSchema(Schema):
    name = fields.Str(required=False)
    description = fields.Str(required=False)


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
    @decorators.endpoint(
        path="/study",
        summary="List of studies to which you have access",
        responses={
            200: "List of studies successfully retrieved",
        },
    )
    @decorators.marshal_with(StudyOutput(many=True), code=200)
    def get(self, uuid: Optional[str] = None) -> Response:

        graph = neo4j.get_instance()

        nodeset = graph.Study.nodes.order_by()
        if uuid is not None:
            nodeset = nodeset.filter(uuid=uuid)
            study = graph.Study.nodes.get_or_none(uuid=uuid)
            self.verifyStudyAccess(study, read=True)

        data = []
        for t in nodeset.all():

            access, motivation = self.verifyStudyAccess(t, read=True, raiseError=False)
            # log.debug("access {} to study {} for {}",access,t.name,motivation)
            if not access:
                continue

            study = {
                "uuid": t.uuid,
                "name": t.name,
                "description": t.description,
                "datasets": len(t.datasets),
            }
            # study["attributes"]["access_verification"] = motivation --> it's still useful?

            data.append(study)

        return self.response(data)

    @decorators.auth.require()
    # {'custom_parameters': ['Study']}
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
        except FileExistsError as exc:
            # just in case..it's almost impossible the same uuid was already used for an other study
            study.delete()
            raise Conflict(str(exc))

        return self.response(study.uuid)

    @decorators.auth.require()
    # {'custom_parameters': ['Study']}
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

        return self.empty_response()
