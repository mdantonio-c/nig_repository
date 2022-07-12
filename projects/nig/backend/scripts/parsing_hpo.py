import warnings

import pronto
from pronto import Ontology
from restapi.config import IMPORT_PATH
from restapi.connectors.neo4j.parser import NodeDump, RelationDump

nodes = NodeDump("HPO", fields=["hpo_id:string", "label:string", "description:string"])

relations = RelationDump(
    "HPO", "IS_CHILD_OF", "HPO", fields=["hpo_id", "hpo_id"], ignore_indexes=True
)

cl = Ontology(f"{IMPORT_PATH}/hp.obo")
for hpo in cl:
    # this warnings seems to not affect our use case since we are not retrieving relationships with indexing
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="indexing an ontology to retrieve a relationship will not be supported in future versions, use `Ontology.get_relationship` directly.",
        )
        # to prevent errors when tries to access relationships instead of terms
        if not isinstance(cl[hpo], pronto.relationship.Relationship):
            nodes.dump(cl[hpo].id, cl[hpo].name, cl[hpo].definition or "N/A")
            # print(f"{cl[hpo].id} , {type(cl[hpo])}")

            for s in list(cl[hpo].subclasses(distance=1)):  # type: ignore
                if cl[hpo].id != s.id:
                    relations.dump(cl[hpo].id, s.id)

nodes.store()
relations.store()
