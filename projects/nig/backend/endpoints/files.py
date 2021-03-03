import os
from typing import Optional

from flask import request
from nig.endpoints import FILE_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import celery, neo4j
from restapi.exceptions import NotFound
from restapi.rest.definition import Response
from restapi.services.uploader import Uploader

# from restapi.utilities.logs import log


class Files(NIGEndpoint):

    labels = ["file"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/dataset/<dataset_uuid>/files",
        summary="Obtain information on a single file",
        responses={
            200: "File information successfully retrieved",
            404: "This file cannot be found or you are not authorized to access",
        },
    )
    @decorators.endpoint(
        path="/file/<file_uuid>",
        summary="Obtain information on a single file",
        responses={
            200: "File information successfully retrieved",
            404: "This file cannot be found or you are not authorized to access",
        },
    )
    def get(
        self, dataset_uuid: Optional[str] = None, file_uuid: Optional[str] = None
    ) -> Response:

        graph = neo4j.get_instance()
        # celery = self.get_service_instance('celery')

        if dataset_uuid is not None:
            dataset = graph.Dataset.nodes.get_or_none(uuid=dataset_uuid)
            self.verifyDatasetAccess(dataset, read=True)

            study = self.getSingleLinkedNode(dataset.parent_study)
            self.verifyStudyAccess(study, error_type="Dataset", read=True)

        elif file_uuid is not None:
            file = graph.File.nodes.get_or_none(uuid=file_uuid)
            if file is None:
                raise NotFound(FILE_NOT_FOUND)

            dataset = self.getSingleLinkedNode(file.dataset)
            self.verifyDatasetAccess(dataset, error_type="File", read=True)

            study = self.getSingleLinkedNode(dataset.parent_study)
            self.verifyStudyAccess(study, error_type="File", read=True)

        path = self.getPath(study=study.uuid, dataset=dataset.uuid)

        irods_data = self.user_icom.list(path=path, detailed=True)

        data = []
        # task = None
        for file in dataset.files.all():
            if file.name not in irods_data:
                continue

            # row = irods_data[file.name]
            row = self.getJsonResponse({})
            row["attributes"] = irods_data[file.name]
            row["attributes"]["type"] = file.type
            # already obtained live from irods
            # row['attributes']['size'] = file.size
            if file.status == "completed" or file.status == "SUCCESS":
                row["attributes"]["status"] = file.status

            # To be re-evaluated
            # else:
            #     if file.task_id is None:
            #         task = None
            #     else:
            #         task = celery.AsyncResult(file.task_id)
            #     if task is not None and str(task) != "None":
            #         row["attributes"]["status"] = task.status
            #     elif file.status is None:
            #         row["attributes"]["status"] = "SUCCESS"
            #     else:
            #         row["attributes"]["status"] = file.status

            if file.metadata:
                row["attributes"]["metadata"] = file.metadata
            data.append(row)

        return self.response(data)

    @decorators.auth.require()
    @decorators.endpoint(
        path="/file/<uuid>",
        summary="Delete a file",
        responses={
            200: "File successfully deleted",
            404: "This file cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this file",
        },
    )
    @decorators.database_transaction
    def delete(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        # INIT #
        file = graph.File.nodes.get_or_none(uuid=uuid)
        if file is None:
            raise NotFound(FILE_NOT_FOUND)
        dataset = self.getSingleLinkedNode(file.dataset)
        self.verifyDatasetAccess(dataset, error_type="File")
        study = self.getSingleLinkedNode(dataset.parent_study)
        self.verifyDatasetAccess(study, error_type="File")
        path = self.getPath(study=study.uuid, dataset=dataset.uuid, file=file.name)

        file.delete()

        self.admin_icom.remove(path, recursive=True)

        return self.empty_response()


class FileUpload(Uploader, NIGEndpoint):

    labels = ["file"]

    @decorators.auth.require()
    # {'parameters': [
    #     {'name': 'flowFilename', 'required': True, 'in': 'query', 'type': 'string'},
    #     {'name': 'flowChunkNumber', 'required': True, 'in': 'query', 'type': 'integer'},
    #     {'name': 'flowTotalChunks', 'required': True, 'in': 'query', 'type': 'integer'},
    #     {'name': 'flowChunkSize', 'required': True, 'in': 'query', 'type': 'integer'}
    # ]}
    @decorators.endpoint(
        path="/dataset/<uuid>/files/upload",
        summary="Upload a file into a dataset",
        responses={
            200: "File successfully uploaded",
        },
    )
    @decorators.database_transaction
    def post(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        chunk_number = int(self.get_input(single_parameter="flowChunkNumber"))
        chunk_total = int(self.get_input(single_parameter="flowTotalChunks"))
        chunk_size = int(self.get_input(single_parameter="flowChunkSize"))
        filename = self.get_input(single_parameter="flowFilename")

        abs_fname, secure_name = self.ngflow_upload(
            filename,
            "/uploads",
            request.files["file"],
            chunk_number,
            chunk_size,
            chunk_total,
            overwrite=True,
        )

        # TO FIX: what happens if last chunk doesn't arrive as last?
        if chunk_number == chunk_total:

            dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
            self.verifyDatasetAccess(dataset)

            study = self.getSingleLinkedNode(dataset.parent_study)
            self.verifyStudyAccess(study, error_type="Dataset")

            name = filename
            name = os.path.basename(name)

            properties = {"name": name, "status": "init"}
            file = graph.File(**properties).save()

            file.dataset.connect(dataset)

            path = self.getPath(study=study.uuid, dataset=dataset.uuid, file=file.name)

            stage_path = "???"  # no longer used
            irods_groups = "???"  # no longer used
            dataPath = "???"  # => file path?
            c = celery.get_instance()
            task = c.celery_app.send_task(
                "import_file",
                args=[
                    file.uuid,
                    stage_path,
                    path,
                    "File",
                    abs_fname,
                    self.irods_user,
                    irods_groups,
                    dataPath,
                ],
                countdown=10,
            )
            file.task_id = task.id
            file.status = "importing"
            file.save()

            return self.response(file.uuid)

        return self.response("", code=202)
