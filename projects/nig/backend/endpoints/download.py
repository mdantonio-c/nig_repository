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

FILE_TO_DOWNLOAD = ["bam", "g.vcf"]


class ResultDownload(NIGEndpoint):

    labels = ["download"]

    @decorators.auth.require()
    @decorators.use_kwargs(
        {"file": fields.Str(required=True, validate=validate.OneOf(FILE_TO_DOWNLOAD))},
        location="query",
    )
    @decorators.endpoint(
        path="dataset/<uuid>/download",
        summary="Download analysis results",
        responses={200: "Found the file to download", 404: "File not found"},
    )
    # 200: {'schema': {'$ref': '#/definitions/Fileoutput'}}
    def get(self, uuid: str, user: User, file: str) -> Response:

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

        # check if the output dir exists and if it is not empty
        if not dataset_output_dir.is_dir():
            raise NotFound("Directory for dataset output not found")

        filepath: Optional[Path] = None
        for f in dataset_output_dir.iterdir():
            if f.suffix == f".{file}":
                filepath = f
                break

        if not filepath:
            raise NotFound(f"file .{file} for dataset {uuid} not found")

        # save the action in the log event
        # self.log_event(self.events.download, filepath)

        # download the file as a response attachment
        return send_from_directory(
            dataset_output_dir, filepath.name, as_attachment=True
        )
