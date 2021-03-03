from nig.endpoints import NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j
from restapi.rest.definition import Response

# from restapi.utilities.logs import log


class PublicStats(NIGEndpoint):

    labels = ["stats"]

    @staticmethod
    def get_count(graph: neo4j.NeoModel, query: str) -> int:

        result = graph.cypher(query)
        for row in result:
            return int(row[0])

    def get_group_count(graph: neo4j.NeoModel, query: str) -> int:

        result = graph.cypher(query)
        data = {}
        for row in result:
            key = row[0]
            if key is None:
                continue
            data[key] = row[1]

        return int(data)

    @decorators.endpoint(
        path="/stats/public",
        summary="Retrieve the repository statistics",
        responses={
            200: "Statistics successfully retrieved",
        },
    )
    def get(self) -> Response:

        graph = neo4j.get_instance()

        # Probably we can make it better...
        filter_user = """
u.email <> 'm.dantonio@cineca.it'
and u.email <> 'test_user1@cineca.it'
"""

        num_users = (
            """
MATCH (u:User)
WHERE %s
RETURN count(u)
"""
            % filter_user
        )

        num_studies = (
            """
MATCH (u:User)<-[:IS_OWNED_BY]-(s:Study)
WHERE %s
RETURN count(s)
"""
            % filter_user
        )

        num_datasets = (
            """
MATCH (u:User)<-[:IS_OWNED_BY]-(d:Dataset)
WHERE %s
RETURN count(d)
"""
            % filter_user
        )

        num_files = (
            """
MATCH (u:User)<-[:IS_OWNED_BY]-(d:Dataset)-[]-(f:File)
WHERE %s
RETURN count(f)
"""
            % filter_user
        )

        #         num_files_by_type = """
        # MATCH (u:User)<-[:IS_OWNED_BY]-(d:Dataset)-[]-(f:File)
        # WHERE %s
        # RETURN f.type, count(f)
        # """ % filter_user

        num_datasets_with_vcf = (
            """
MATCH (u:User)<-[:IS_OWNED_BY]-(d:Dataset)-[]-(:Phenotype)
WHERE %s
WITH u, d limit 15000
MATCH (d)-[]-(f:File)
WHERE f.name ENDS WITH ".vcf" AND NOT(f.name ENDS WITH ".g.vcf")
return count(d)
"""
            % filter_user
        )

        data = {}
        data["num_users"] = self.get_count(graph, num_users)
        data["num_studies"] = self.get_count(graph, num_studies)

        data["num_datasets"] = self.get_count(graph, num_datasets)
        # data['num_datasets_per_user'] = \
        #     self.get_group_count(graph, num_datasets_per_user)

        data["num_datasets_with_vcf"] = self.get_count(graph, num_datasets_with_vcf)

        data["num_files"] = self.get_count(graph, num_files)
        # data['num_files_by_type'] = self.get_group_count(graph, num_files_by_type)

        return self.response(data)


class PrivateStats(NIGEndpoint):

    labels = ["stats"]

    def get_count(self, graph, query):

        result = graph.cypher(query)
        for row in result:
            return row[0]

    def get_group_count(self, graph, query):

        result = graph.cypher(query)
        data = {}
        for row in result:
            key = row[0]
            if key is None:
                continue
            data[key] = row[1]

        return data

    @decorators.auth.require()
    @decorators.endpoint(
        path="/stats/private",
        summary="Retrieve the repository statistics",
        responses={
            200: "Statistics successfully retrieved",
        },
    )
    def get(self):

        graph = neo4j.get_instance()

        # Probably we can make it better
        filter_user = """
u.email <> 'm.dantonio@cineca.it'
and u.email <> 'test_user1@cineca.it'
"""

        num_users = (
            """
MATCH (u:User)
WHERE %s
RETURN count(u)
"""
            % filter_user
        )

        num_studies = (
            """
MATCH (u:User)<-[:IS_OWNED_BY]-(s:Study)
WHERE %s
RETURN count(s)
"""
            % filter_user
        )

        num_datasets = (
            """
MATCH (u:User)<-[:IS_OWNED_BY]-(d:Dataset)
WHERE %s
RETURN count(d)
"""
            % filter_user
        )

        num_datasets_per_group = (
            """
MATCH (g:Group)<-[:BELONGS_TO]-(u:User)<-[:IS_OWNED_BY]-(d:Dataset)
WHERE %s
RETURN g.fullname, count(d)

"""
            % filter_user
        )

        num_files = (
            """
MATCH (u:User)<-[:IS_OWNED_BY]-(d:Dataset)-[]-(f:File)
WHERE %s
RETURN count(f)
"""
            % filter_user
        )

        #         num_files_by_type = """
        # MATCH (u:User)<-[:IS_OWNED_BY]-(d:Dataset)-[]-(f:File)
        # WHERE %s
        # RETURN f.type, count(f)
        # """ % filter_user

        num_datasets_with_vcf = (
            """
MATCH (u:User)<-[:IS_OWNED_BY]-(d:Dataset)-[]-(:Phenotype)
WHERE %s
WITH u, d limit 15000
MATCH (d)-[]-(f:File)
WHERE f.name ENDS WITH ".vcf" AND NOT(f.name ENDS WITH ".g.vcf")
return count(d)
"""
            % filter_user
        )

        num_datasets_with_vcf_per_group = (
            """
MATCH (:Group)<-[:BELONGS_TO]-(u:User)<-[:IS_OWNED_BY]-(d:Dataset)-[]-(:Phenotype)
WHERE %s
WITH i, d limit 15000
MATCH (d)-[]-(f:File)
WHERE f.name ENDS WITH ".vcf" AND NOT(f.name ENDS WITH ".g.vcf")
return i.fullname, count(d)
"""
            % filter_user
        )

        num_datasets_with_gvcf = (
            """
MATCH (u:User)<-[:IS_OWNED_BY]-(d:Dataset)-[]-(f:File)
WHERE %s
    AND (f.name ENDS WITH ".g.vcf" OR f.name =~ ".*\\\\.g.vcf\\\\..*")
    AND NOT f.name ENDS WITH ".tbi"
return count(d)
"""
            % filter_user
        )

        num_datasets_with_gvcf_per_group = (
            """
MATCH (:Group)<-[:BELONGS_TO]-(u:User)<-[:IS_OWNED_BY]-(d:Dataset)
WHERE %s
WITH i, d limit 15000
MATCH (d)-[]-(f:File)
WHERE (f.name ENDS WITH ".g.vcf" OR f.name =~ ".*\\\\.g.vcf\\\\..*")
       AND NOT f.name ENDS WITH ".tbi"
return i.fullname, count(d)
"""
            % filter_user
        )

        num_genes = "MATCH (n:Gene) return count(n)"
        num_variants = "MATCH (n:Variant) return count(n)"

        data = {}
        data["num_users"] = self.get_count(graph, num_users)
        data["num_studies"] = self.get_count(graph, num_studies)

        data["num_datasets"] = self.get_count(graph, num_datasets)
        data["num_datasets_per_group"] = self.get_group_count(
            graph, num_datasets_per_group
        )

        data["num_datasets_with_vcf"] = self.get_count(graph, num_datasets_with_vcf)
        data["num_datasets_with_vcf_per_group"] = self.get_group_count(
            graph, num_datasets_with_vcf_per_group
        )

        data["num_datasets_with_gvcf"] = self.get_count(graph, num_datasets_with_gvcf)
        data["num_datasets_with_gvcf_per_group"] = self.get_group_count(
            graph, num_datasets_with_gvcf_per_group
        )

        data["num_files"] = self.get_count(graph, num_files)
        # data['num_files_by_type'] = self.get_group_count(graph, num_files_by_type)

        data["num_genes"] = self.get_count(graph, num_genes)
        data["num_variants"] = self.get_count(graph, num_variants)

        return self.response(data)
