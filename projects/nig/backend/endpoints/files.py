import os
import pathlib
import re
from typing import Any

from nig.endpoints import FILE_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import BadRequest, NotFound
from restapi.models import Schema, fields
from restapi.rest.definition import Response
from restapi.services.authentication import User
from restapi.services.uploader import Uploader
from restapi.utilities.logs import log


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
    def get(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset, user=user, read=True)

        study = dataset.parent_study.single()

        self.verifyStudyAccess(study, user=user, error_type="Dataset", read=True)

        path = self.getPath(user=user, dataset=dataset, read=True)

        directory_data = os.listdir(path)

        data = []

        for file in dataset.files.all():
            if file.name not in directory_data:
                file.status = "unknown"
                file.save()
            else:
                # check if the status is correct
                if file.status == "unknown":
                    filepath = self.getPath(user=user, file=file, read=True)
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
    def get(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        file = graph.File.nodes.get_or_none(uuid=uuid)
        if file is None:
            raise NotFound(FILE_NOT_FOUND)

        dataset = file.dataset.single()
        self.verifyDatasetAccess(dataset, user=user, error_type="File", read=True)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, user=user, error_type="File", read=True)

        # check if file exists in the folder
        path = self.getPath(user=user, dataset=dataset, read=True)

        directory_data = os.listdir(path)

        if file.name not in directory_data:
            file.status = "unknown"
            file.save()
        else:
            # check if the status is correct
            if file.status == "unknown":
                filepath = self.getPath(user=user, file=file, read=True)
                if not os.path.getsize(filepath) == file.size:
                    file.status = "importing"
                else:
                    file.status = "uploaded"
                file.save()

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
    def delete(self, uuid: str, user: User) -> Response:

        graph = neo4j.get_instance()

        file = graph.File.nodes.get_or_none(uuid=uuid)
        if file is None:
            raise NotFound(FILE_NOT_FOUND)
        dataset = file.dataset.single()
        self.verifyDatasetAccess(dataset, user=user, error_type="File")
        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, user=user, error_type="File")
        path = self.getPath(user=user, file=file)

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
        responses={
            200: "File uploaded succesfully",
            404: "File not found",
            500: "Fail in uploading file",
        },
    )
    @decorators.database_transaction
    def put(self, uuid: str, filename: str, user: User) -> Response:

        graph = neo4j.get_instance()
        # check permission
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset, user=user)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, user=user, error_type="Dataset")

        # get the file
        file = None
        for f in dataset.files.all():
            if f.name == filename:
                file = f
        if not file:
            raise NotFound(FILE_NOT_FOUND)
        file.status = "importing"
        file.save()

        path = self.getPath(user=user, dataset=dataset)
        completed, response = self.chunk_upload(pathlib.Path(path), filename)
        log.debug("check {}", response)

        if completed:
            # check the final size
            filepath = self.getPath(user=user, file=file)
            if not os.path.getsize(filepath) == file.size:
                log.debug(
                    "size expected: {},actual size: {}",
                    file.size,
                    os.path.getsize(filepath),
                )
                file.delete()
                os.remove(filepath)
                # in this case we return the response and not raise the exception to not have the database rollback due to database_transaction decorator (i want the file database entry to be deleted and the rollback will prevent that)
                return self.response(
                    "File has not been uploaded correctly: final size does not correspond to total size. Please try a new upload",
                    code=500,
                )
            file.status = "uploaded"
            file.save()
            self.log_event(
                self.events.create,
                file,
                {
                    "operation": f"Completed upload for {filename} file in {uuid} dataset"
                },
            )

        return response

    @decorators.auth.require()
    @decorators.init_chunk_upload
    @decorators.endpoint(
        path="/dataset/<uuid>/files/upload",
        summary="Upload a file into a dataset",
        responses={
            201: "Upload initialized",
            400: "File extension not allowed",
            409: "File already exists",
        },
    )
    @decorators.database_transaction
    def post(self, uuid: str, name: str, user: User, **kwargs: Any) -> Response:

        # check permissions
        graph = neo4j.get_instance()
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset, user=user)

        study = dataset.parent_study.single()
        self.verifyStudyAccess(study, error_type="Dataset")

        path = self.getPath(user=user, dataset=dataset)

        # check if the filename is correct
        name_pattern = r"([a-zA-Z0-9]+)_(R[12]).fastq.gz"
        if not re.search(name_pattern, name):
            raise BadRequest(
                "Filename should follow the correct naming convention SampleName_R1/R2.fastq.gz"
            )

        # set the allowed file format
        self.set_allowed_exts(["gz"])

        filebase, fileext = os.path.splitext(name)

        properties = {
            "name": name,
            "size": kwargs["size"],
            "type": fileext.strip("."),
            "status": "init",
        }

        file = graph.File(**properties).save()

        file.dataset.connect(dataset)

        self.log_event(
            self.events.create,
            file,
            {"operation": f"Accepted upload for {name} file in {uuid} dataset"},
        )

        return self.init_chunk_upload(pathlib.Path(path), name, force=False)
