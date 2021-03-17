from typing import Dict, Optional, Union

from nig.endpoints import NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.models import Schema, fields
from restapi.rest.definition import Response

# from restapi.utilities.logs import log


class PublicStatsOutput(Schema):
    num_users = fields.Integer(required=False)
    num_studies = fields.Integer(required=False)
    num_datasets = fields.Integer(required=False)
    num_datasets_with_vcf = fields.Integer(required=False)
    num_files = fields.Integer(required=False)


class PrivateStatsOutput(Schema):
    num_users = fields.Integer(required=False)
    num_studies = fields.Integer(required=False)
    num_datasets = fields.Integer(required=False)
    num_datasets_per_group = fields.Dict(
        required=False, keys=fields.Str(), values=fields.Integer()
    )
    num_datasets_with_vcf = fields.Integer(required=False)
    num_datasets_with_vcf_per_group = fields.Dict(
        required=False, keys=fields.Str(), values=fields.Integer()
    )
    num_datasets_with_gvcf = fields.Integer(required=False)
    num_datasets_with_gvcf_per_group = fields.Dict(
        required=False, keys=fields.Str(), values=fields.Integer()
    )
    num_files = fields.Integer(required=False)


def get_filter_by_group() -> Optional[str]:
    # group used for test or, in general, groups we don't want to be counted in stats
    group_to_filter = []
    filter_group = ""
    if group_to_filter:
        for g in group_to_filter:
            if not filter_group:
                filter_group = f"WHERE g.fullname <> '{g}' "
            else:
                filter_group += f"and g.fullname <> '{g}' "

    return filter_group


query_dictionary = {
    "count_users": {
        "match": "MATCH(u: User)-[: BELONGS_TO]->(g:Group)",
        "count": "RETURN count(u)",
    },
    "count_studies": {
        "match": "MATCH (g:Group)<-[:BELONGS_TO]-(u:User)<-[:IS_OWNED_BY]-(s:Study)",
        "count": "RETURN count(s)",
    },
    "count_datasets": {
        "match": "MATCH (g:Group)<-[:BELONGS_TO]-(u:User)<-[:IS_OWNED_BY]-(d:Dataset)",
        "count": "RETURN count(d)",
        "count_per_group": "RETURN g.fullname, count(d)",
    },
    "count_files": {
        "match": "MATCH (g:Group)<-[:BELONGS_TO]-(u:User)<-[:IS_OWNED_BY]-(d:Dataset)-[]-(f:File)",
        "count": "RETURN count(f)",
    },
    "count_dataset_with_vcf": {
        "match": [
            "MATCH (g:Group)<-[:BELONGS_TO]-(u:User)<-[:IS_OWNED_BY]-(d:Dataset)-[]-(:Phenotype) ",
            "filter_by_group",
            "WITH g, d limit 15000 ",
            "MATCH (d)-[]-(f:File) ",
            "WHERE f.name ENDS WITH '.vcf' AND NOT(f.name ENDS WITH '.g.vcf') ",
        ],
        "count": "RETURN count(d)",
        "count_per_group": "RETURN g.fullname, count(d)",
    },
    "count_dataset_with_gvcf": {
        "match": [
            "MATCH (g:Group)<-[:BELONGS_TO]-(u:User)<-[:IS_OWNED_BY]-(d:Dataset) ",
            "filter_by_group",
            "WITH g, d limit 15000 ",
            "MATCH (d)-[]-(f:File)",
            "WHERE (f.name ENDS WITH '.g.vcf' OR f.name =~ '.*\\\\.g.vcf\\\\..*') ",
            "AND NOT f.name ENDS WITH '.tbi'",
        ],
        "count": "RETURN count(d)",
        "count_per_group": "RETURN g.fullname, count(d)",
    },
}


def count_nodes(graph: neo4j.NeoModel, key: str) -> int:
    filter_group = get_filter_by_group()
    if (
        type(query_dictionary[key]["match"]) == list
    ):  # exception in case of advanced queries who needs the filter by group in between
        query = ""
        for m in query_dictionary[key]["match"]:
            if (
                m != "filter_by_group"
            ):  # this expression in the list means where the filter group(if any) has to be inserted
                query += m
            else:
                query += filter_group
        query += query_dictionary[key]["count"]
    else:
        query = f"{query_dictionary[key]['match']} {filter_group} {query_dictionary[key]['count']}"

    result = graph.cypher(query)

    for row in result:
        return int(row[0])

    return 0


def count_by_group(graph: neo4j.NeoModel, key: str) -> Dict[str, int]:
    filter_group = get_filter_by_group()

    if (
        type(query_dictionary[key]["match"]) == list
    ):  # exception in case of advanced queries who needs the filter by group in between
        query = ""
        for m in query_dictionary[key]["match"]:
            if (
                m != "filter_by_group"
            ):  # this expression in the list means where the filter group(if any) has to be inserted
                query += m
            else:
                query += filter_group
        query += query_dictionary[key]["count_per_group"]
    else:
        query = f"{query_dictionary[key]['match']} {filter_group} {query_dictionary[key]['count_per_group']}"

    result = graph.cypher(query)
    data: Dict[str, int] = {}
    for row in result:
        key = row[0]
        if key is None:
            continue
        data[key] = int(row[1])

    return data


class PublicStats(NIGEndpoint):

    labels = ["stats"]

    @decorators.endpoint(
        path="/stats/public",
        summary="Retrieve the repository statistics",
        responses={
            200: "Statistics successfully retrieved",
        },
    )
    @decorators.marshal_with(PublicStatsOutput, code=200)
    def get(self) -> Response:

        graph = neo4j.get_instance()

        data = {}
        data["num_users"] = count_nodes(graph, "count_users")
        data["num_studies"] = count_nodes(graph, "count_studies")

        data["num_datasets"] = count_nodes(graph, "count_datasets")
        data["num_datasets_with_vcf"] = count_nodes(graph, "count_dataset_with_vcf")

        data["num_files"] = count_nodes(graph, "count_files")

        return self.response(data)


class PrivateStats(NIGEndpoint):

    labels = ["stats"]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/stats/private",
        summary="Retrieve the repository statistics",
        responses={
            200: "Statistics successfully retrieved",
        },
    )
    @decorators.marshal_with(PrivateStatsOutput, code=200)
    def get(self) -> Response:

        graph = neo4j.get_instance()

        data: Dict[str, Union[int, Dict[str, int]]] = {}
        data["num_users"] = count_nodes(graph, "count_users")
        data["num_studies"] = count_nodes(graph, "count_studies")

        data["num_datasets"] = count_nodes(graph, "count_datasets")
        data["num_datasets_per_group"] = count_by_group(graph, "count_datasets")

        data["num_datasets_with_vcf"] = count_nodes(graph, "count_dataset_with_vcf")
        data["num_datasets_with_vcf_per_group"] = count_by_group(
            graph, "count_dataset_with_vcf"
        )

        data["num_datasets_with_gvcf"] = count_nodes(graph, "count_dataset_with_gvcf")
        data["num_datasets_with_gvcf_per_group"] = count_by_group(
            graph, "count_dataset_with_gvcf"
        )

        data["num_files"] = count_nodes(graph, "count_files")

        return self.response(data)
