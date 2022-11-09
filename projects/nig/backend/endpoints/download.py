from pathlib import Path
from typing import Optional

from flask import send_from_directory
from nig.endpoints import FILE_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import NotFound
from restapi.models import fields, validate
from restapi.rest.definition import Response
from restapi.services.authentication import User
from restapi.services.download import Downloader

FILE_TO_DOWNLOAD = ["bam", "g.vcf"]
RESOURCE_FOLDER = {"bam": "bwa", "g.vcf": "gatk_gvcf"}


class ResultDownload(NIGEndpoint):

    labels = ["download"]

    @decorators.auth.require(allow_access_token_parameter=True)
    @decorators.use_kwargs(
        {
            "file": fields.Str(
                required=True, validate=validate.OneOf(FILE_TO_DOWNLOAD)
            ),
            "get_total_size": fields.Bool(required=False),
        },
        location="query",
    )
    @decorators.endpoint(
        path="dataset/<uuid>/download",
        summary="Download analysis results",
        responses={200: "Found the file to download", 404: "File not found"},
    )
    # 200: {'schema': {'$ref': '#/definitions/Fileoutput'}}
    def get(
        self, uuid: str, user: User, file: str, get_total_size: bool = False
    ) -> Response:

        # check dataset ownership
        graph = neo4j.get_instance()
        dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
        self.verifyDatasetAccess(dataset, user=user, read=False)

        study = dataset.parent_study.single()

        self.verifyStudyAccess(study, user=user, error_type="Dataset", read=True)

        # check if the analysis is completed
        if dataset.status != "COMPLETED":
            raise NotFound(
                "Results non found: The dataset analysis has not been completed"
            )

        # get the file location
        dataset_output_dir = self.getPath(
            user=user, dataset=dataset, get_output_dir=True
        )

        resource_dir = Path(dataset_output_dir, RESOURCE_FOLDER[file])

        # check if the output dir exists and if it is not empty
        if not resource_dir.is_dir():
            raise NotFound("Directory for dataset output not found")

        filepath: Optional[Path] = None
        for f in resource_dir.iterdir():
            if f.suffix == f".{file}" or f.name.endswith(f".{file}.gz"):
                filepath = f
                break

        if not filepath:
            raise NotFound(f"file .{file} for dataset {uuid} not found")

        if get_total_size:
            # return the total size of the file to download
            total_size = filepath.stat().st_size
            return self.response(total_size)

        # save the action in the log event
        self.log_event(self.events.access, dataset, {"downloaded_file": str(filepath)})

        # download the file as a response attachment
        # return send_from_directory(resource_dir, filepath.name, as_attachment=True)
        return Downloader.send_file_streamed(filepath.name, subfolder=resource_dir)
