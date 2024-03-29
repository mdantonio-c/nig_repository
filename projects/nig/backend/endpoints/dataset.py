import shutil
from datetime import datetime
from typing import Any, Dict, Optional, Type, Union

import pytz
from nig.endpoints import PHENOTYPE_NOT_FOUND, TECHMETA_NOT_FOUND, NIGEndpoint
from nig.endpoints._injectors import (
    verify_dataset_access,
    verify_dataset_status_update,
    verify_study_access,
)
from restapi import decorators
from restapi.connectors import neo4j
from restapi.customizer import FlaskRequest
from restapi.exceptions import BadRequest, Conflict, NotFound
from restapi.models import Schema, fields, validate
from restapi.rest.definition import Response
from restapi.services.authentication import User
from restapi.utilities.logs import log


class TechnicalMetadata(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)


class Phenotype(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)


# Output schema
class DatasetOutput(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    description = fields.Str(required=False)
    status = fields.Str(required=False)
    status_update = fields.Str(required=False)
    error_message = fields.Str(required=False)
    joint_analysis = fields.Bool(required=False)
    technical = fields.Neo4jRelationshipToSingle(TechnicalMetadata)
    phenotype = fields.Neo4jRelationshipToSingle(Phenotype)
    files = fields.Neo4jRelationshipToCount()
    readonly = fields.Bool(dump_default=True)
    # for now only the number of related files,
    # can be useful also a list of some files metadata?
    # virtual files?


def getInputSchema(request: FlaskRequest, is_post: bool) -> Type[Schema]:
    graph = neo4j.get_instance()
    # as defined in Marshmallow.schema.from_dict
    attributes: Dict[str, Union[fields.Field, type]] = {}

    attributes["name"] = fields.Str(required=is_post)
    attributes["description"] = fields.Str(required=is_post)
    if request:
        if is_post:
            study_uuid = request.view_args["uuid"]
            study = graph.Study.nodes.get_or_none(uuid=study_uuid)
        else:
            dataset_uuid = request.view_args["uuid"]
            dataset = graph.Dataset.nodes.get_or_none(uuid=dataset_uuid)
            study = dataset.parent_study.single()

        phenotype_keys = []
        phenotype_labels = []

        for p in study.phenotypes.all():
            phenotype_keys.append(p.uuid)
            phenotype_labels.append(p.name)

        if len(phenotype_keys) == 1:
            default_phenotype = phenotype_keys[0]
        else:
            default_phenotype = None

        if not is_post:
            # add option to remove the technical
            phenotype_keys.append("-1")
            phenotype_labels.append(" - ")

        attributes["phenotype"] = fields.Str(
            required=False,
            allow_none=True,
            dump_default=default_phenotype,
            validate=validate.OneOf(choices=phenotype_keys, labels=phenotype_labels),
        )

        techmeta_keys = []
        techmeta_labels = []

        for t in study.technicals.all():
            techmeta_keys.append(t.uuid)
            techmeta_labels.append(t.name)

        if len(techmeta_keys) == 1:
            default_techmeta = techmeta_keys[0]
        else:
            default_techmeta = None

        if not is_post:
            # add option to remove the technical
            techmeta_keys.append("-1")
            techmeta_labels.append(" - ")

        attributes["technical"] = fields.Str(
            required=False,
            allow_none=True,
            dump_default=default_techmeta,
            validate=validate.OneOf(choices=techmeta_keys, labels=techmeta_labels),
        )

    return Schema.from_dict(attributes, name="DatasetDefinition")


def getPOSTInputSchema(request: FlaskRequest) -> Type[Schema]:
    return getInputSchema(request, True)


def getPUTInputSchema(request: FlaskRequest) -> Type[Schema]:
    return getInputSchema(request, False)


class Datasets(NIGEndpoint):
    labels = ["dataset"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<uuid>/datasets",
        summary="Obtain the list of datasets in a study",
        responses={
            200: "Dataset list successfully retrieved",
        },
    )
    @decorators.marshal_with(DatasetOutput(many=True), code=200)
    def get(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, user=user, read=True)

        data = []
        for dataset in study.datasets.all():

            if not self.verifyDatasetAccess(
                dataset, user=user, read=True, raiseError=False
            ):
                continue
            dataset_el = {}
            dataset_el["uuid"] = dataset.uuid
            dataset_el["name"] = dataset.name
            dataset_el["description"] = dataset.description
            dataset_el["status"] = dataset.status
            dataset_el["error_message"] = dataset.error_message
            dataset_el["technical"] = dataset.technical
            dataset_el["phenotype"] = dataset.phenotype
            dataset_el["files"] = dataset.files
            dataset_el["joint_analysis"] = dataset.joint_analysis

            # check if the date of the status is available. If not get the dataset last modified date
            if dataset.status_update:
                status_update = dataset.status_update
            else:
                status_update = dataset.modified
            dataset_el["status_update"] = status_update.strftime("%d-%m-%Y, %H:%M")

            owner = dataset.ownership.single()
            if owner == user:
                dataset_el["readonly"] = False

            for group in owner.belongs_to.all():
                if group.members.is_connected(user):
                    dataset_el["readonly"] = False

            data.append(dataset_el)

        return self.response(data)


class Dataset(NIGEndpoint):
    @decorators.auth.require()
    @decorators.endpoint(
        path="/dataset/<uuid>",
        summary="Obtain information on a single dataset",
        responses={
            200: "Dataset information successfully retrieved",
            404: "This dataset cannot be found or you are not authorized to access",
        },
    )
    @decorators.marshal_with(DatasetOutput, code=200)
    def get(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset, user=user, read=True)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, user=user, error_type="Dataset", read=True)

        self.log_event(self.events.access, dataset)
        return self.response(dataset)

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<uuid>/datasets",
        summary="Create a new dataset in a study",
        responses={
            200: "The uuid of the new dataset",
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
        description: str,
        # should be an instance of neo4j.Study,
        # but typing is still not working with neomodel
        study: Any,
        user: User,
        phenotype: Optional[str] = None,
        technical: Optional[str] = None,
    ) -> Response:

        graph = neo4j.get_instance()

        kwargs = {"name": name, "description": description}
        dataset = graph.Dataset(**kwargs).save()

        dataset.ownership.connect(user)
        dataset.parent_study.connect(study)
        if phenotype:
            kwargs["phenotype"] = phenotype
            phenotype = study.phenotypes.get_or_none(uuid=phenotype)
            if phenotype is None:  # pragma: no cover
                raise NotFound(PHENOTYPE_NOT_FOUND)
            dataset.phenotype.connect(phenotype)
        if technical:
            kwargs["technical"] = technical
            technical = study.technicals.get_or_none(uuid=technical)
            if technical is None:  # pragma: no cover
                raise NotFound(TECHMETA_NOT_FOUND)
            dataset.technical.connect(technical)

        path = self.getPath(user=user, dataset=dataset)

        try:
            path.mkdir(parents=True, exist_ok=False)
        # Almost impossible to have the same uuid was already used for an other study
        except FileExistsError as exc:  # pragma: no cover
            dataset.delete()
            raise Conflict(str(exc))

        self.log_event(self.events.create, dataset, kwargs)

        return self.response(dataset.uuid)

    @decorators.auth.require()
    @decorators.endpoint(
        path="/dataset/<uuid>",
        summary="Modify a dataset",
        responses={
            200: "Dataset successfully modified",
            404: "This dataset cannot be found or you are not authorized to access",
        },
    )
    @decorators.preload(callback=verify_dataset_access)
    @decorators.use_kwargs(getPUTInputSchema)
    @decorators.database_transaction
    def put(
        self,
        uuid: str,
        # should be an instance of neo4j.Study,
        # but typing is still not working with neomodel
        study: Any,
        # should be an instance of neo4j.Dataset,
        # but typing is still not working with neomodel
        dataset: Any,
        user: User,
        name: Optional[str] = None,
        description: Optional[str] = None,
        phenotype: Optional[str] = None,
        technical: Optional[str] = None,
    ) -> Response:

        kwargs = {}
        if phenotype:
            kwargs["phenotype"] = phenotype
            if previous := dataset.phenotype.single():
                dataset.phenotype.disconnect(previous)

            if phenotype != "-1":
                phenotype = study.phenotypes.get_or_none(uuid=phenotype)

                if phenotype is None:  # pragma: no cover
                    raise NotFound(PHENOTYPE_NOT_FOUND)

                dataset.phenotype.connect(phenotype)

        if technical:
            kwargs["technical"] = technical
            if previous := dataset.technical.single():
                dataset.technical.disconnect(previous)

            if technical != "-1":
                technical = study.technicals.get_or_none(uuid=technical)

                if technical is None:  # pragma: no cover
                    raise NotFound(TECHMETA_NOT_FOUND)

                dataset.technical.connect(technical)
        if name:
            kwargs["name"] = name
            dataset.name = name
        if description:
            kwargs["description"] = description
            dataset.description = description

        dataset.save()

        self.log_event(self.events.modify, dataset, kwargs)

        return self.empty_response()

    @decorators.auth.require()
    @decorators.endpoint(
        path="/dataset/<uuid>",
        summary="Modify the status of a dataset",
        responses={
            200: "Status successfully modified",
            400: "Status can't be modified",
            404: "This dataset cannot be found or you are not authorized to access",
        },
    )
    @decorators.preload(callback=verify_dataset_status_update)
    @decorators.use_kwargs(
        {
            "status": fields.Str(
                required=True, validate=validate.OneOf(["UPLOAD COMPLETED", "-1"])
            )
        }
    )
    @decorators.database_transaction
    def patch(
        self,
        uuid: str,
        study: Any,
        dataset: Any,
        status: str,
        user: User,
    ) -> Response:

        # patch can only be done on dataset with status UPLOAD COMPLETED
        if (
            dataset.status
            and dataset.status != "UPLOAD COMPLETED"
            and not self.auth.is_admin(user)
        ):
            raise BadRequest(f"The status of dataset {dataset.name} cannot be modified")

        if status == "-1":
            dataset.status = None
        else:
            dataset.status = status

        dataset.status_update = datetime.now(pytz.utc)
        dataset.save()

        self.log_event(self.events.modify, dataset, {"status": status})

        return self.empty_response()

    @decorators.auth.require()
    @decorators.endpoint(
        path="/dataset/<uuid>",
        summary="Delete a dataset",
        responses={
            200: "Dataset successfully deleted",
            404: "This dataset cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this dataset",
        },
    )
    @decorators.database_transaction
    def delete(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        # INIT #
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset, user=user)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, user=user, error_type="Dataset")
        input_path = self.getPath(user=user, dataset=dataset)
        output_path = self.getPath(user=user, dataset=dataset, get_output_dir=True)

        for f in dataset.files.all():
            f.delete()

        dataset.delete()

        # remove the dataset folder
        shutil.rmtree(input_path)
        # if it's present remove the dataset folder
        if output_path.is_dir():
            shutil.rmtree(output_path)

        self.log_event(self.events.delete, dataset)

        return self.empty_response()
