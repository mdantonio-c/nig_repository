import os
import pathlib
from typing import Any

from nig.endpoints import FILE_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import celery, neo4j
from restapi.exceptions import BadRequest, NotFound, ServerError
from restapi.models import Schema, fields
from restapi.rest.definition import Response
from restapi.services.uploader import Uploader

# from restapi.utilities.logs import log


class FileOutput(Schema):
    uuid = fields.Str(required=True)
    name = fields.Str(required=True)
    type = fields.Str(required=False)
    size = fields.Integer(required=False)
    status = fields.Str(required=False)
    # metadata?


class Files(NIGEndpoint):

    labels = ["file"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/dataset/<uuid>/files",
        summary="Obtain information on a single file",
        responses={
            200: "File information successfully retrieved",
            404: "This file cannot be found or you are not authorized to access",
        },
    )
    @decorators.marshal_with(FileOutput(many=True), code=200)
    def get(self, uuid: str) -> Response:

        graph = neo4j.get_instance()
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset, read=True)

        study = dataset.parent_study.single()

        self.verifyStudyAccess(study, error_type="Dataset", read=True)

        path = self.getPath(dataset=dataset)

        directory_data = os.listdir(path)

        data = []

        for file in dataset.files.all():
            if file.name not in directory_data:
                file.status = "unknown"
                file.save()
            else:
                # check if the status is correct
                if file.status == "unknown":
                    filepath = self.getPath(file=file)
                    if not os.path.getsize(filepath) == file.size:
                        file.status = "importing"
                    else:
                        file.status = "uploaded"
                    file.save()
            data.append(file)

        return self.response(data)


class SingleFile(NIGEndpoint):

    labels = ["file"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/file/<uuid>",
        summary="Obtain information on a single file",
        responses={
            200: "File information successfully retrieved",
            404: "This file cannot be found or you are not authorized to access",
        },
    )
    @decorators.marshal_with(FileOutput, code=200)
    def get(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        file = graph.File.nodes.get_or_none(uuid=uuid)
        if file is None:
            raise NotFound(FILE_NOT_FOUND)

        dataset = file.dataset.single()
        self.verifyDatasetAccess(dataset, error_type="File", read=True)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, error_type="File", read=True)

        self.log_event(self.events.access, file)

        return self.response(file)

    @decorators.auth.require()
    @decorators.endpoint(
        path="/file/<uuid>",
        summary="Delete a file",
        responses={
            200: "File successfully deleted",
            404: "This file cannot be found or you are not authorized to access",
        },
    )
    @decorators.database_transaction
    def delete(self, uuid: str) -> Response:

        graph = neo4j.get_instance()

        file = graph.File.nodes.get_or_none(uuid=uuid)
        if file is None:
            raise NotFound(FILE_NOT_FOUND)
        dataset = file.dataset.single()
        self.verifyDatasetAccess(dataset, error_type="File")
        study = dataset.parent_study.single()
        self.verifyDatasetAccess(study, error_type="File")
        path = self.getPath(file=file)

        file.delete()

        if os.path.exists(path):
            os.remove(path)

        self.log_event(self.events.delete, file)

        return self.empty_response()


class FileUpload(Uploader, NIGEndpoint):

    labels = ["file"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/dataset/<uuid>/files/upload/<filename>",
        summary="Upload a file into a dataset",
        responses={200: "File uploaded succesfully", 500: "Fail in uploading file"},
    )
    @decorators.database_transaction
    def put(self, uuid: str, filename: str) -> Response:

        graph = neo4j.get_instance()
        # check permission
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, error_type="Dataset")

        # get the file
        file = graph.File.nodes.get_or_none(name=filename)
        file.status = "importing"
        file.save()

        path = self.getPath(dataset=dataset)
        completed, response = self.chunk_upload(pathlib.Path(path), filename)

        if completed:
            # check the final size
            filepath = self.getPath(file=file)
            if not os.path.getsize(filepath) == file.size:
                file.delete()
                os.remove(filepath)
                raise ServerError(
                    "File has not been uploaded correctly: final size does not correspond to total size. Please try a new upload"
                )
            file.status = "uploaded"
            file.save()
            specs = f"Completed upload for {filename} file in {uuid} dataset"

            self.log_event(self.events.create, file, specs)

        return response

    @decorators.auth.require()
    @decorators.init_chunk_upload
    @decorators.endpoint(
        path="/dataset/<uuid>/files/upload",
        summary="Upload a file into a dataset",
        responses={201: "Upload initialized", 400: "File already exists"},
    )
    @decorators.database_transaction
    def post(self, uuid: str, name: str, **kwargs: Any) -> Response:

        # check permissions
        graph = neo4j.get_instance()
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, error_type="Dataset")

        path = self.getPath(dataset=dataset)

        # set the allowed file format
        self.set_allowed_exts(["gz"])

        filebase, fileext = os.path.splitext(name)

        # check if a file with the same name alresdy exists in the db
        file = graph.File.nodes.get_or_none(name=name)
        if file:
            raise BadRequest("A file with the same name already exists")

        properties = {
            "name": name,
            "size": kwargs["size"],
            "type": fileext.strip("."),
            "status": "init",
        }

        file = graph.File(**properties).save()

        file.dataset.connect(dataset)

        specs = f"Accepted upload for {name} file in {uuid} dataset"

        self.log_event(self.events.create, file, specs)

        return self.init_chunk_upload(pathlib.Path(path), name)
