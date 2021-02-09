import os

from flask import request
from nig.endpoints import RESOURCE_NOT_FOUND, NIGEndpoint
from restapi import decorators
from restapi.connectors import celery, neo4j
from restapi.exceptions import NotFound
from restapi.services.uploader import Uploader


class Resources(NIGEndpoint):

    labels = ["file"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<uuid>/resources",
        summary="List of resource files contained in a study",
        responses={
            200: "List of resources successfully retrieved",
        },
    )
    def get(self, uuid):

        graph = neo4j.get_instance()

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study, read=True)
        nodeset = study.resources

        path = self.getPath(study=study.uuid)

        irods_data = self.user_icom.list(path=path, recursive=False)

        data = []
        for resource in nodeset.all():
            row = {}
            if resource.name in irods_data:
                row = irods_data[resource.name]
            else:
                row = dict()
                row["name"] = resource.name
            row["type"] = resource.type
            row["content_length"] = resource.size
            row["status"] = resource.status
            data.append(row)

        return self.response(data)

    @decorators.auth.require()
    @decorators.endpoint(
        path="/resource/<uuid>",
        summary="Delete a resource file from a study",
        responses={
            200: "Resource successfully deleted",
            404: "This resource cannot be found or you are not authorized to access",
        },
    )
    @decorators.graph_transactions
    def delete(self, uuid):

        graph = neo4j.get_instance()

        resource = graph.Resource.nodes.get_or_none(uuid=uuid)
        if resource is None:
            raise NotFound(RESOURCE_NOT_FOUND)
        study = self.getSingleLinkedNode(resource.study)
        self.verifyStudyAccess(study)

        for v in resource.virtual_file.all():
            v.delete()

        resource.delete()

        path = self.getPath(study=study.uuid, file=resource.name)
        # you should verify for object existence
        try:
            self.admin_icom.remove(path, recursive=False)
        except BaseException:
            pass

        return self.empty_response()


class ResourcesUpload(Uploader, NIGEndpoint):

    labels = ["file"]

    @decorators.auth.require()
    # {'parameters': [
    # {'name': 'flowFilename', 'required': True, 'in': 'query', 'type': 'string'},
    # {'name': 'flowChunkNumber', 'required': True, 'in': 'query', 'type': 'integer'},
    # {'name': 'flowTotalChunks', 'required': True, 'in': 'query', 'type': 'integer'},
    # {'name': 'flowChunkSize', 'required': True, 'in': 'query', 'type': 'integer'}
    # ]}
    @decorators.endpoint(
        path="/study/<uuid>/resources/upload",
        summary="Upload a resource file into a study",
        responses={
            200: "Resource file successfully uploaded",
        },
    )
    @decorators.graph_transactions
    def post(self, uuid):

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

            study = graph.Study.nodes.get_or_none(uuid=uuid)
            self.verifyStudyAccess(study)

            name = os.path.basename(filename)

            properties = {"name": name, "status": "init"}
            resource = graph.Resource(**properties).save()

            resource.study.connect(study)

            path = self.getPath(study=study.uuid, file=resource.name)

            stage_path = "???"  # no longer used
            irods_groups = "???"  # no longer used
            dataPath = "???"  # => file path?

            c = celery.get_instance()
            task = c.celery_app.send_task(
                "import_file",
                args=[
                    resource.uuid,
                    stage_path,
                    path,
                    "Resource",
                    abs_fname,
                    self.irods_user,
                    irods_groups,
                    dataPath,
                ],
                countdown=10,
            )
            resource.task_id = task.id
            resource.status = "importing"
            resource.save()

            return self.response(resource.uuid)
        return self.response("", code=202)
