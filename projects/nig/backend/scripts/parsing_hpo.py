import csv

from pronto import Ontology
from restapi.connectors import neo4j

cl = Ontology("/data/hp.obo")
output_nodes = "/data/hpo_nodes.tsv"
output_rel = "/data/hpo_rel.tsv"
with open(output_nodes, "wt") as out_nodes:
    with open(output_rel, "wt") as out_rels:
        tsv_node_writer = csv.writer(out_nodes, delimiter="\t")
        tsv_rel_writer = csv.writer(out_rels, delimiter="\t")
        # tsv_node_writer.writerow(['id', 'name','definition','xref'])
        tsv_node_writer.writerow(["id", "name", "definition"])
        tsv_rel_writer.writerow(["id", "son"])
        for hpo in cl:
            # xrefs_list = ""
            # for x in cl[hpo].xrefs:
            # 	xrefs_list += f"{x.id}, "
            # tsv_node_writer.writerow([cl[hpo].id, cl[hpo].name,cl[hpo].definition,xrefs_list])
            tsv_node_writer.writerow([cl[hpo].id, cl[hpo].name, cl[hpo].definition])
            sons = list(cl[hpo].subclasses())
            for s in sons:
                tsv_rel_writer.writerow([cl[hpo].id, s.id])

# enter data in neo4j
graph = neo4j.get_instance()
query_for_nodes = "USING PERIODIC COMMIT 1000 LOAD CSV WITH HEADERS FROM 'file:///repo/hpo_nodes.tsv' AS line FIELDTERMINATOR '\t' CREATE (:HPO { hpo_id: line.id, label: line.name, description: line.definition});"

graph.cypher(query_for_nodes)
# create relationships
query_for_rel = "USING PERIODIC COMMIT 1000 LOAD CSV WITH HEADERS FROM 'file:///repo/hpo_rel.tsv' AS line FIELDTERMINATOR '\t' MATCH (child: HPO {hpo_id: line.son}), (parent: HPO {hpo_id: line.id}) CREATE (child)-[r:IS_CHILD_OF]->(parent)"
graph.cypher(query_for_rel)
