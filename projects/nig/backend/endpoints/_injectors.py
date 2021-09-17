from typing import Any, Dict

from nig.endpoints import PHENOTYPE_NOT_FOUND, NIGEndpoint
from restapi.connectors import neo4j
from restapi.exceptions import NotFound
from restapi.services.authentication import User


def verify_study_access(endpoint: NIGEndpoint, uuid: str, user: User) -> Dict[str, Any]:
    graph = neo4j.get_instance()
    study = graph.Study.nodes.get_or_none(uuid=uuid)
    endpoint.verifyStudyAccess(study, user=user)
    return {"study": study}


def verify_dataset_access(
    endpoint: NIGEndpoint, uuid: str, user: User
) -> Dict[str, Any]:
    graph = neo4j.get_instance()
    dataset = graph.Dataset.nodes.get_or_none(uuid=uuid)
    endpoint.verifyDatasetAccess(dataset, user=user)

    study = dataset.parent_study.single()
    endpoint.verifyStudyAccess(study, user=user, error_type="Dataset")

    return {"dataset": dataset, "study": study}


def verify_phenotype_access(
    endpoint: NIGEndpoint, uuid: str, user: User
) -> Dict[str, Any]:
    graph = neo4j.get_instance()
    phenotype = graph.Phenotype.nodes.get_or_none(uuid=uuid)
    if phenotype is None:
        raise NotFound(PHENOTYPE_NOT_FOUND)
    study = phenotype.defined_in.single()
    endpoint.verifyStudyAccess(study, user=user, error_type="Phenotype")
    return {"phenotype": phenotype, "study": study}
