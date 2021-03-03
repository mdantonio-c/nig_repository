import re

from nig.endpoints import NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.rest.definition import Response


class City(NIGEndpoint):

    labels = ["miscellaneous"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/city/<query>",
        summary="List of existing cities matching a substring query",
        responses={
            200: "Matching cities successfully retrieved",
        },
    )
    def get(self, query: str) -> Response:
        graph = neo4j.get_instance()

        data = []

        cypher = "MATCH (geo:GeoData)"
        cypher += " WHERE geo.city =~ '(?i).*%s.*'" % query
        cypher += " RETURN geo ORDER BY geo.population DESC"
        cypher += " LIMIT 50"

        result = graph.cypher(cypher)
        for row in result:
            geo = graph.GeoData.inflate(row[0])
            name = f"{geo.city} ({geo.region} - {geo.country})"
            data.append({"id": geo.uuid, "city": name})

        return self.response(data)


class HPO(NIGEndpoint):

    labels = ["miscellaneous"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/hpo/<query>",
        summary="List of existing hpo terms matching a substring query",
        responses={
            200: "Matching hpo terms successfully retrieved",
        },
    )
    def get(self, query: str) -> Response:

        graph = neo4j.get_instance()

        data = []
        cypher = "MATCH (hpo:HPO)"

        if query.startswith("HP:") and len(query) >= 4:
            cypher += " WHERE hpo.hpo_id =~ '(?i).*%s.*'" % query
        else:
            cypher += " WHERE hpo.label =~ '(?i).*%s.*'" % query
        cypher += " RETURN hpo ORDER BY hpo.hpo_id DESC"
        cypher += " LIMIT 50"

        result = graph.cypher(cypher)
        for row in result:
            hpo = graph.HPO.inflate(row[0])
            name = f"{hpo.hpo_id} ({hpo.label})"
            data.append({"hpo_id": hpo.hpo_id, "label": name})

        return self.response(data)


class MainEffect(NIGEndpoint):

    labels = ["miscellaneous"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/maineffect/<query>",
        summary="List of existing variant main effects matching a substring query",
        responses={
            200: "Matching variant main effects successfully retrieved",
        },
    )
    def get(self, query: str) -> Response:

        graph = neo4j.get_instance()

        data = []
        cypher = "MATCH (variant:Variant)"
        cypher += " WHERE variant.MainEffect =~ '(?i).*%s.*'" % query
        cypher += " RETURN distinct variant.MainEffect"
        cypher += " ORDER BY variant.MainEffect ASC"
        cypher += " LIMIT 50"

        result = graph.cypher(cypher)
        for row in result:
            effect = row[0]
            data.append({"id": effect, "label": effect})

        return self.response(data)


class EnrichmentKit(NIGEndpoint):

    labels = ["miscellaneous"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/erichmentkit/<query>",
        summary="List of existing enrichment kits matching a substring query",
        responses={
            200: "Matching enrichment kits successfully retrieved",
        },
    )
    def get(self, query: str) -> Response:

        kits = []

        kits.append("Agilent - sureselect_clinical")
        kits.append("Agilent - sureselect_focused")
        kits.append("Agilent - sureselect_inherited")
        kits.append("Agilent - sureselectV4")
        kits.append("Agilent - sureselectV5")
        kits.append("Agilent - sureselectV5_utr")
        kits.append("Agilent - sureselectV6")
        kits.append("Agilent - sureselectV6_cosmic")
        kits.append("Agilent - sureselectV6_utr")
        kits.append("NimbleGen - Exome_UTR")
        kits.append("NimbleGen - hg18vcrome")
        kits.append("NimbleGen - MED")
        kits.append("NimbleGen - SeqCapEZ_Exome_v2")
        kits.append("NimbleGen - SeqCapEZ_Exome_v3")
        kits.append("Illumina - nextera_rapid")
        kits.append("Illumina - nextera_rapid_expanded")
        kits.append("Illumina - nextera_rapid_v1.2")
        kits.append("Illumina - truseq_exome")
        kits.append("Illumina - truseq_rapid_exome")
        kits.append("Illumina - trusight")
        kits.append("Life Technologies (Ion) - Ion AmpliSeq™ Exome RDY Kit 1x8")
        kits.append("Life Technologies (Ion) - Ion AmpliSeq™ Exome RDY Kit 4x2")
        # kits.append("Other")

        data = []
        for t in kits:
            if re.search(query, t, re.IGNORECASE):
                data.append({"value": t, "name": t})

        return self.response(data)
