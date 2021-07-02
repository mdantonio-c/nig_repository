from pronto import Ontology
from restapi.config import IMPORT_PATH
from restapi.connectors.neo4j.parser import NodeDump, RelationDump

nodes = NodeDump("HPO", fields=["hpo_id:string", "label:string", "description:string"])

relations = RelationDump(
    "HPO", "IS_CHILD_OF", "HPO", fields=["hpo_id", "hpo_id"], ignore_indexes=True
)

cl = Ontology(f"{IMPORT_PATH}/hp.obo")
for hpo in cl:
    nodes.dump(cl[hpo].id, cl[hpo].name, cl[hpo].definition or "N/A")

    for s in list(cl[hpo].subclasses(distance=1)):  # type: ignore
        if cl[hpo].id != s.id:
            relations.dump(cl[hpo].id, s.id)

nodes.store()
relations.store()
