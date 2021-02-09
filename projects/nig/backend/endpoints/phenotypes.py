from nig.endpoints import PHENOTYPE_NOT_FOUND, NIGEndpoint
from nig.time import date_from_string
from restapi import decorators
from restapi.connectors import neo4j
from restapi.exceptions import BadRequest, NotFound

# from restapi.connectors import celery

# from restapi.utilities.logs import log


class Phenotypes(NIGEndpoint):

    # schema_expose = True
    labels = ["phenotype"]

    def link_hpo(self, graph, phenotype, properties):
        ids = self.parseAutocomplete(properties, "HPO", id_key="hpo_id", split_char=",")

        if ids is None:
            return

        for p in phenotype.hpo.all():
            phenotype.hpo.disconnect(p)

        for id in ids:
            try:
                hpo = graph.HPO.nodes.get(hpo_id=id)
                phenotype.hpo.connect(hpo)
            except graph.HPO.DoesNotExist:
                pass

    def link_geodata(self, graph, phenotype, properties):
        ids = self.parseAutocomplete(properties, "birthplace", id_key="id")

        if ids is None:
            return

        for p in phenotype.birth_place.all():
            phenotype.birth_place.disconnect(p)

        for id in ids:
            try:
                geo = graph.GeoData.nodes.get(uuid=id)
                phenotype.birth_place.connect(geo)
            except graph.GeoData.DoesNotExist:
                pass

    def validate_input(self, properties, schema):

        if "name" in properties:
            if properties["name"] == "":
                raise BadRequest("Name cannot be empty")

        if "sex" in properties:
            s = properties["sex"]
            allowed = ["male", "female"]

            if s not in allowed:
                raise BadRequest("Allowed values for sex are: male, female")

    @decorators.auth.require()
    @decorators.endpoint(
        path="/study/<study_uuid>/phenotypes",
        summary="Obtain information on a single phenotype",
        responses={
            200: "Phenotype information successfully retrieved",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    @decorators.endpoint(
        path="/phenotype/<phenotype_uuid>",
        summary="Obtain information on a single phenotype",
        responses={
            200: "Phenotype information successfully retrieved",
            404: "This phenotype cannot be found or you are not authorized to access",
        },
    )
    def get(self, study_uuid=None, phenotype_uuid=None):

        graph = neo4j.get_instance()

        if phenotype_uuid is not None:
            phenotype = graph.Phenotype.nodes.get_or_none(uuid=phenotype_uuid)
            if phenotype is None:
                raise NotFound(PHENOTYPE_NOT_FOUND)
            study = self.getSingleLinkedNode(phenotype.defined_in)
            self.verifyStudyAccess(study, error_type="Phenotype", read=True)
            nodeset = graph.Phenotype.nodes.filter(uuid=phenotype_uuid)

        elif study_uuid is not None:
            study = graph.Study.nodes.get_or_none(uuid=study_uuid)
            self.verifyStudyAccess(study, read=True)
            nodeset = study.phenotypes

        data = []
        for t in nodeset.all():

            phenotype = self.getJsonResponse(t)

            if "relationships" in phenotype and "hpo" in phenotype["relationships"]:
                for h in phenotype["relationships"]["hpo"]:
                    h["attributes"]["public"] = ""
                    hh = graph.HPO.nodes.get_or_none(hpo_id=h["attributes"]["hpo_id"])
                    for hhh in hh.generalized_parent.all():
                        if hhh.hide_node:
                            continue
                        h["attributes"]["public"] += "{} ({}); ".format(
                            hhh.hpo_id,
                            hhh.label,
                        )

            data.append(phenotype)

        return self.response(data)

    @decorators.auth.require()
    # {'custom_parameters': ['Phenotype']}
    @decorators.endpoint(
        path="/study/<uuid>/phenotypes",
        summary="Create a new phenotype in a study",
        responses={
            200: "The uuid of the new phenotype",
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
        self.validate_input(v, schema)

        study = graph.Study.nodes.get_or_none(uuid=uuid)
        self.verifyStudyAccess(study)
        properties = self.read_properties(schema, v)

        properties["unique_name"] = self.createUniqueIndex(
            study.uuid, properties["name"]
        )

        if "birthday" in properties:
            properties["birthday"] = date_from_string(properties["birthday"])

        if "deathday" in properties:
            properties["deathday"] = date_from_string(properties["deathday"])

        phenotype = graph.Phenotype(**properties).save()

        phenotype.defined_in.connect(study)

        self.link_geodata(graph, phenotype, v)
        self.link_hpo(graph, phenotype, v)

        # c = celery.get_instance()
        # c.celery_app.send_task(
        #     "link_variants", args=[phenotype.uuid], countdown=5
        # )

        return self.response(phenotype.uuid)

    @decorators.auth.require()
    # {'custom_parameters': ['Phenotype']}
    @decorators.endpoint(
        path="/phenotype/<uuid>",
        summary="Modify a phenotype",
        responses={
            200: "Phenotype successfully modified",
            404: "This phenotype cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this phenotype",
        },
    )
    @decorators.graph_transactions
    def put(self, uuid):

        graph = neo4j.get_instance()

        v = self.get_input()
        schema = self.get_endpoint_custom_definition()
        self.validate_input(v, schema)

        phenotype = graph.Phenotype.nodes.get_or_none(uuid=uuid)
        if phenotype is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)
        study = self.getSingleLinkedNode(phenotype.defined_in)
        self.verifyStudyAccess(study, error_type="Phenotype")
        if "birthday" in v:
            if v["birthday"] == "":
                v["birthday"] = None
            else:
                v["birthday"] = date_from_string(v["birthday"])

        if "deathday" in v:
            if v["deathday"] == "":
                v["deathday"] = None
            else:
                v["deathday"] = date_from_string(v["deathday"])

        self.update_properties(phenotype, schema, v)
        phenotype.unique_name = self.createUniqueIndex(study.uuid, phenotype.name)

        phenotype.save()
        self.link_geodata(graph, phenotype, v)
        self.link_hpo(graph, phenotype, v)

        # c = celery.get_instance()
        # c.celery_app.send_task(
        #     "link_variants", args=[phenotype.uuid], countdown=5
        # )

        return self.empty_response()

    @decorators.auth.require()
    @decorators.endpoint(
        path="/phenotype/<uuid>",
        summary="Delete a phenotype",
        responses={
            200: "Phenotype successfully deleted",
            404: "This phenotype cannot be found or you are not authorized to access",
            403: "You are not authorized to perform actions on this phenotype",
        },
    )
    @decorators.graph_transactions
    def delete(self, uuid):

        graph = neo4j.get_instance()

        phenotype = graph.Phenotype.nodes.get_or_none(uuid=uuid)
        if phenotype is None:
            raise NotFound(PHENOTYPE_NOT_FOUND)
        study = self.getSingleLinkedNode(phenotype.defined_in)
        self.verifyStudyAccess(study, error_type="Phenotype")

        phenotype.delete()

        return self.empty_response()
