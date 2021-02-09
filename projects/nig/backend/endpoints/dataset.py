from nig.endpoints import (
    DATASET_NOT_FOUND,
    PHENOTYPE_NOT_FOUND,
    STUDY_NOT_FOUND,
    TECHMETA_NOT_FOUND,
    NIGEndpoint,
)
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import BadRequest, NotFound

# from restapi.utilities.logs import log


class Dataset(NIGEndpoint):

    labels = ["dataset"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<study_uuid>/datasets",
        summary="Obtain information on a single dataset",
        responses={
            200: "Dataset information successfully retrieved",
            404: "This dataset cannot be found or you are not authorized to access",
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
    def get(self, study_uuid=None, dataset_uuid=None):

        graph = neo4j.get_instance()

        dataset = None
        study = None
        acl = None

        if study_uuid is not None:
            study = graph.Study.nodes.get_or_none(uuid=study_uuid)
            self.verifyStudyAccess(study, read=True)

        elif dataset_uuid is not None:
            dataset = graph.Dataset.nodes.get_or_none(uuid=dataset_uuid)
            self.verifyDatasetAccess(dataset, read=True)

            study = self.getSingleLinkedNode(dataset.parent_study)
            self.verifyStudyAccess(study, error_type="Dataset", read=True)

            path = self.getPath(study=study.uuid, dataset=dataset.uuid)
            acl = self.user_icom.get_permissions(path)

        if study is None:
            raise NotFound(STUDY_NOT_FOUND)

        path = self.getPath(study=study.uuid)

        # collections = self.user_icom.list(path=path, recursive=False)

        if dataset_uuid is not None:
            nodeset = graph.Dataset.nodes.filter(uuid=dataset_uuid)
        else:
            nodeset = study.datasets

        data = []
        for t in nodeset.all():

            if not self.verifyDatasetAccess(t, read=True, raiseError=False):
                continue

            if not t.parent_study.is_connected(study):
                continue

            dataset = self.getJsonResponse(t, max_relationship_depth=2)

            dataset["attributes"]["nfiles"] = len(t.files)
            # dataset['attributes']['nvariants'] = self.getLinkedVariants(t)

            if acl is not None:
                dataset["attributes"]["acl"] = acl["ACL"]
                dataset["attributes"]["acl_inheritance"] = acl["inheritance"]

            data.append(dataset)

        if dataset_uuid is not None and len(data) < 1:
            raise NotFound(DATASET_NOT_FOUND)

        return self.response(data)

    @decorators.auth.require()
    # {'custom_parameters': ['Dataset']}
    @decorators.endpoint(
        path="/study/<uuid>/datasets",
        summary="Create a new dataset in a study",
        responses={
            200: "The uuid of the new dataset",
            404: "This study cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this study",
        },
    )
    @decorators.graph_transactions
    def post(self, uuid):

        graph = neo4j.get_instance()
        v = self.get_input()
        if len(v) == 0:
            raise BadRequest("Empty input")

        schema = self.get_endpoint_custom_definition()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study)

        properties = self.read_properties(schema, v)

        current_user = self.get_current_user()

        properties["unique_name"] = self.createUniqueIndex(
            study.uuid, properties["name"]
        )
        dataset = graph.Dataset(**properties).save()

        dataset.ownership.connect(current_user)
        dataset.parent_study.connect(study)

        path = self.getPath(study=study.uuid, dataset=dataset.uuid)

        # to be implemented
        self.mkdir(path)

        return self.response(dataset.uuid)

    @decorators.auth.require()
    # {'custom_parameters': ['Dataset']}
    @decorators.endpoint(
        path="/dataset/<uuid>",
        summary="Modify a dataset",
        responses={
            200: "Dataset successfully modified",
            404: "This dataset cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this dataset",
        },
    )
    @decorators.graph_transactions
    def put(self, uuid):

        graph = neo4j.get_instance()
        v = self.get_input()
        schema = self.get_endpoint_custom_definition()

        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset)

        study = self.getSingleLinkedNode(dataset.parent_study)
        self.verifyStudyAccess(study, error_type="Dataset")

        self.update_properties(dataset, schema, v)
        dataset.unique_name = self.createUniqueIndex(study.uuid, dataset.name)

        dataset.save()

        if "phenotype" in v:

            phenotype_id = v["phenotype"]

            if str(phenotype_id) == "-1":
                for p in dataset.phenotype.all():
                    dataset.phenotype.disconnect(p)
            else:

                phenotype = graph.Phenotype.nodes.get_or_none(uuid=phenotype_id)

                if phenotype is None:
                    raise NotFound(PHENOTYPE_NOT_FOUND)

                for p in dataset.phenotype.all():
                    dataset.phenotype.disconnect(p)

                dataset.phenotype.connect(phenotype)

        if "technical" in v:

            technical_id = v["technical"]

            if str(technical_id) == "-1":
                for p in dataset.technical.all():
                    dataset.technical.disconnect(p)
            else:

                technical = graph.TechnicalMetadata.nodes.get_or_none(uuid=technical_id)

                if technical is None:
                    raise NotFound(TECHMETA_NOT_FOUND)

                for p in dataset.technical.all():
                    dataset.technical.disconnect(p)

                dataset.technical.connect(technical)

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
    def delete(self, uuid):

        graph = neo4j.get_instance()

        # INIT #
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset)

        study = self.getSingleLinkedNode(dataset.parent_study)
        self.verifyStudyAccess(study, error_type="Dataset")
        path = self.getPath(study=study.uuid, dataset=dataset.uuid)

        for f in dataset.files.all():
            f.delete()

        dataset.delete()

        self.admin_icom.remove(path, recursive=True)

        return self.empty_response()
