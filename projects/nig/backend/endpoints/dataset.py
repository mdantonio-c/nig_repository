import os
import shutil
from typing import Any, Optional

from nig.endpoints import PHENOTYPE_NOT_FOUND, TECHMETA_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import BadRequest, Conflict, NotFound
from restapi.models import Schema, fields
from restapi.rest.definition import Response

# from restapi.utilities.logs import log


class Dataset(NIGEndpoint):

    # Output schema
    class DatasetOutput(Schema):
        uuid = fields.Str(required=True)
        name = fields.Str(required=True)
        description = fields.Str(required=False)
        nfiles = fields.Int()
        # for now only the number of related files, can be useful also a list of some files metadata?
        # virtual files?

    # input schema
    class DatasetInputSchema(Schema):
        name = fields.Str(required=True)
        description = fields.Str(required=False)

    class DatasetPutSchema(Schema):
        name = fields.Str(required=False)
        description = fields.Str(required=False)
        phenotype_uuid = fields.Str(required=False)
        technical_uuid = fields.Str(required=False)

    labels = ["dataset"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<study_uuid>/datasets",
        summary="Obtain the list of datasets in a study",
        responses={
            200: "Dataset list successfully retrieved",
        },
    )
    @decorators.endpoint(
        path="/dataset/<dataset_uuid>",
        summary="Obtain information on a single dataset",
        responses={
            200: "Dataset information successfully retrieved",
            404: "This dataset cannot be found or you are not authorized to access",
        },
    )
    @decorators.marshal_with(DatasetOutput(many=True), code=200)
    def get(
        self, study_uuid: Optional[str] = None, dataset_uuid: Optional[str] = None
    ) -> Response:

        graph = neo4j.get_instance()

        if study_uuid:
            study = graph.Study.nodes.get_or_none(uuid=study_uuid)
            self.verifyStudyAccess(study, read=True)
            nodeset = study.datasets

        elif dataset_uuid:
            dataset = graph.Dataset.nodes.get_or_none(uuid=dataset_uuid)
            self.verifyDatasetAccess(dataset, read=True)

            study = self.getSingleLinkedNode(dataset.parent_study)
            self.verifyStudyAccess(study, error_type="Dataset", read=True)

            nodeset = graph.Dataset.nodes.filter(uuid=dataset_uuid)
        else:  # pragma: no cover
            raise BadRequest("Missing study or dataset ID")

        data = []
        for dataset in nodeset.all():

            if not self.verifyDatasetAccess(dataset, read=True, raiseError=False):
                continue

            if not dataset.parent_study.is_connected(study):
                continue

            dataset_el = {
                "uuid": dataset.uuid,
                "name": dataset.name,
                "description": dataset.description,
                "nfiles": len(dataset.files),
            }

            data.append(dataset_el)

        return self.response(data)

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<uuid>/datasets",
        summary="Create a new dataset in a study",
        responses={
            200: "The uuid of the new dataset",
            404: "This study cannot be found or you are not authorized to access",
        },
    )
    @decorators.graph_transactions
    @decorators.use_kwargs(DatasetInputSchema)
    def post(self, uuid: str, **kwargs: Any) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study)

        current_user = self.get_user()

        dataset = graph.Dataset(**kwargs).save()

        dataset.ownership.connect(current_user)
        dataset.parent_study.connect(study)

        path = self.getPath(dataset=dataset)

        try:
            os.makedirs(path, exist_ok=False)
        # Almost impossible to have the same uuid was already used for an other study
        except FileExistsError as exc:  # pragma: no cover
            dataset.delete()
            raise Conflict(str(exc))

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
    @decorators.use_kwargs(DatasetPutSchema)
    @decorators.graph_transactions
    def put(
        self,
        uuid: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        phenotype_uuid: Optional[str] = None,
        technical_uuid: Optional[str] = None,
    ) -> Response:

        graph = neo4j.get_instance()

        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset)

        study = self.getSingleLinkedNode(dataset.parent_study)
        self.verifyStudyAccess(study, error_type="Dataset")

        if phenotype_uuid:
            if previous := dataset.phenotype.single():
                dataset.phenotype.disconnect(previous)

            if phenotype_uuid != "-1":
                phenotype = graph.Phenotype.nodes.get_or_none(uuid=phenotype_uuid)

                if phenotype is None:
                    raise NotFound(PHENOTYPE_NOT_FOUND)

                dataset.phenotype.connect(phenotype)

        if technical_uuid:
            if previous := dataset.technical.single():
                dataset.technical.disconnect(previous)

            if technical_uuid != "-1":
                technical = graph.TechnicalMetadata.nodes.get_or_none(
                    uuid=technical_uuid
                )

                if technical is None:
                    raise NotFound(TECHMETA_NOT_FOUND)

                dataset.technical.connect(technical)
        if name:
            dataset.name = name
        if description:
            dataset.description = description

        dataset.save()

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
    @decorators.graph_transactions
    def delete(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        # INIT #
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset)

        study = self.getSingleLinkedNode(dataset.parent_study)
        self.verifyStudyAccess(study, error_type="Dataset")
        path = self.getPath(dataset=dataset)

        for f in dataset.files.all():
            f.delete()

        dataset.delete()

        # remove the dataset folder
        shutil.rmtree(path)

        return self.empty_response()
