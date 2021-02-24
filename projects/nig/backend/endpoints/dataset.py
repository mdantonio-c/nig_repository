import os
import shutil
from typing import Dict, Optional, Union

from nig.endpoints import PHENOTYPE_NOT_FOUND, TECHMETA_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import Conflict, NotFound
from restapi.models import (
    Neo4jRelationshipToCount,
    Neo4jRelationshipToSingle,
    Schema,
    fields,
    validate,
)
from restapi.rest.definition import Response

# from restapi.utilities.logs import log


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
    technical = Neo4jRelationshipToSingle(TechnicalMetadata)
    phenotype = Neo4jRelationshipToSingle(Phenotype)
    files = Neo4jRelationshipToCount()
    # for now only the number of related files, can be useful also a list of some files metadata?
    # virtual files?


def getInputSchema(request, is_post):
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
            default=default_phenotype,
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
            default=default_techmeta,
            validate=validate.OneOf(choices=techmeta_keys, labels=techmeta_labels),
        )

    return Schema.from_dict(attributes, name="DatasetDefinition")


def getPOSTInputSchema(request):
    return getInputSchema(request, True)


def getPUTInputSchema(request):
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
    def get(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, read=True)
        nodeset = study.datasets

        data = []
        for dataset in nodeset.all():

            if not self.verifyDatasetAccess(dataset, read=True, raiseError=False):
                continue

            if not dataset.parent_study.is_connected(study):
                continue

            data.append(dataset)

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
    def get(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset, read=True)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, error_type="Dataset", read=True)

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
    @decorators.use_kwargs(getPOSTInputSchema)
    def post(
        self,
        uuid: str,
        name: str,
        description: str,
        phenotype: Optional[str] = None,
        technical: Optional[str] = None,
    ) -> Response:

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study)

        current_user = self.get_user()

        kwargs = {"name": name, "description": description}
        dataset = graph.Dataset(**kwargs).save()

        dataset.ownership.connect(current_user)
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

        path = self.getPath(dataset=dataset)

        try:
            os.makedirs(path, exist_ok=False)
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
    @decorators.use_kwargs(getPUTInputSchema)
    @decorators.database_transaction
    def put(
        self,
        uuid: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        phenotype: Optional[str] = None,
        technical: Optional[str] = None,
    ) -> Response:

        graph = neo4j.get_instance()

        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, error_type="Dataset")

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
        summary="Delete a dataset",
        responses={
            200: "Dataset successfully deleted",
            404: "This dataset cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this dataset",
        },
    )
    @decorators.database_transaction
    def delete(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        # INIT #
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, error_type="Dataset")
        path = self.getPath(dataset=dataset)

        for f in dataset.files.all():
            f.delete()

        dataset.delete()

        # remove the dataset folder
        shutil.rmtree(path)

        self.log_event(self.events.delete, dataset)

        return self.empty_response()
