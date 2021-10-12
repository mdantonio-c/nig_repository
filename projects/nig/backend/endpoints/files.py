import gzip
import re
from pathlib import Path
from typing import Any, Tuple

from nig.endpoints import FILE_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import BadRequest, NotFound, ServerError
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

        data = []

        for file in dataset.files.all():
            if not path.joinpath(file.name).exists():
                file.status = "unknown"
                file.save()
            else:
                # check if the status is correct
                if file.status == "unknown":
                    filepath = self.getPath(user=user, file=file, read=True)
                    if filepath.stat().st_size != file.size:
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

        if not path.joinpath(file.name).exists():
            file.status = "unknown"
            file.save()
        else:
            # check if the status is correct
            if file.status == "unknown":
                filepath = self.getPath(user=user, file=file, read=True)
                if filepath.stat().st_size != file.size:
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

        if path.exists():
            path.unlink()

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
            400: "The uploaded file has an invalid content",
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
        completed, response = self.chunk_upload(Path(path), filename)
        log.debug("check {}", response)
        if completed:
            # check the final size
            filepath = self.getPath(user=user, file=file)
            filesize = filepath.stat().st_size
            # check the final size
            if filesize != file.size:
                log.debug(
                    "size expected: {},actual size: {}",
                    file.size,
                    filesize,
                )
                file.delete()
                graph.db.commit()
                filepath.unlink()
                raise ServerError(
                    "File has not been uploaded correctly: final size does not "
                    "correspond to total size. Please try a new upload",
                )
            # check the content of the file
            file_validation = validate_gzipped_fastq(filepath)
            if not file_validation[0]:
                # delete the file
                file.delete()
                graph.db.commit()
                filepath.unlink()
                raise BadRequest(file_validation[1])
            file.status = "uploaded"
            file.save()
            self.log_event(
                self.events.create,
                file,
                {filename: f"Upload completed in dataset {uuid}"},
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
        self.verifyStudyAccess(study, user=user, error_type="Dataset")

        path = self.getPath(user=user, dataset=dataset)

        # check if the filename is correct
        name_pattern = r"([a-zA-Z0-9]+)_(R[12]).fastq.gz"
        if not re.search(name_pattern, name):
            raise BadRequest(
                "Filename does not follow the correct naming convention: "
                "SampleName_R1/R2.fastq.gz"
            )

        # set the allowed file format
        self.set_allowed_exts(["gz"])

        properties = {
            "name": name,
            "size": kwargs["size"],
            # Currently fixed
            "type": "fastq.gz",
            "status": "init",
        }

        file = graph.File(**properties).save()

        file.dataset.connect(dataset)

        self.log_event(
            self.events.create,
            file,
            {"operation": f"Accepted upload for {name} file in {uuid} dataset"},
        )

        return self.init_chunk_upload(Path(path), name, force=False)


def validate_gzipped_fastq(path: Path) -> Tuple[bool, str]:

    if not path.exists():
        return False, "File does not exist or it is not readable"

    if path.stat().st_size == 0:
        return False, "File is empty"

    try:
        with gzip.open(path, "rt") as f:
            line1 = f.readline().strip()
            if not line1.startswith("@"):
                return False, f"Not a valid fastq file, invalid header: {line1}"
            line2 = f.readline().strip()
            line3 = f.readline().strip()
            if not line3.startswith("+"):
                return False, f"Not a valid fastq file, invalid separator: {line3}"
            line4 = f.readline().strip()
            if len(line2) != len(line4):
                compare = f":\nline2: [{line2}]\nline4: [{line4}]"
                return False, f"Not a valid fastq file, lines lengths differ{compare}"
            line5 = f.readline().strip()
            # line5 will be None if the the fastq only has one read
            if line5 and not line5.startswith("@"):
                return False, f"Not a valid fastq file, invalid header: {line5}"

        return True, "Valid fastq file"
    except gzip.BadGzipFile as bad_gzip:
        return False, str(bad_gzip)
    except UnicodeDecodeError as unicode_error:
        log.error(unicode_error)
        return False, "File is binary"
