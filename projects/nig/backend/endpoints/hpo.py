import re
from typing import Dict, List

from nig.endpoints import NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.rest.definition import Response


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

        data: List[Dict[str, str]] = []

        # Chars whitelist: letters, numbers, colon and hyphen
        if not re.match("^[a-zA-Z0-9:-]+$", query):
            return self.response(data)

        cypher = "MATCH (hpo:HPO)"

        regexp = f"(?i).*{query}.*"
        if query.startswith("HP:") and len(query) >= 4:
            cypher += " WHERE hpo.hpo_id =~ $regexp"
        else:
            cypher += " WHERE hpo.label =~ $regexp"
        cypher += " RETURN hpo ORDER BY hpo.hpo_id DESC"
        cypher += " LIMIT 50"

        result = graph.cypher(cypher, regexp=regexp)
        for row in result:
            hpo = graph.HPO.inflate(row[0])
            data.append({"hpo_id": hpo.hpo_id, "label": hpo.label})

        return self.response(data)
