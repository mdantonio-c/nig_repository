import ast
import time
from datetime import datetime
from typing import Any, Dict, List

import pytz
from restapi.connectors import neo4j
from restapi.connectors.celery import CeleryExt
from restapi.utilities.logs import log


def count_alleles(datasets: List[str], probands: Dict[str, bool]):
    if datasets is None:
        return 0

    alleles = 0

    for d in datasets.values():
        is_proband = probands.get(d, False)
        if is_proband:
            continue
        alleles += 2

    return alleles


# def computeAlleleFrequency(self, node_id):
def computeAlleleFrequency(
    graph: neo4j.NeoModel, variant: Any, datasets: Dict[str, bool]
) -> bool:
    now = time.mktime(datetime.now(pytz.utc).timetuple())

    num_obs = count_alleles(variant.observed, datasets)
    num_nonobs = count_alleles(variant.non_observed, datasets)

    if num_obs == 0 and num_nonobs == 0:
        variant.total_allele = 0
        variant.allele_count = 0
        variant.allele_frequency = 0
        variant.save()
        return False

    total_allele = num_obs + num_nonobs

    allele_count = 0
    num_hom = 0
    num_het = 0
    for d in variant.observed:
        data = variant.observed.get(d)
        GT = data.get("GT")
        num_alleles = int(GT[0:1]) + int(GT[2:3])

        if num_alleles == 1:
            num_het += 1
        elif num_alleles == 2:
            num_hom += 2

        allele_count += num_alleles

    variant.total_allele = total_allele
    variant.allele_count = allele_count
    variant.num_hom = num_hom
    variant.num_het = num_het
    variant.allele_frequency = float(allele_count) / total_allele
    variant.save()

    cypher = """
MATCH (v:Variant) WHERE id(v) = %d
SET v.modified = %f
REMOVE v:ToBeUpdated
        """ % (
        variant.id,
        now,
    )
    graph.cypher(cypher)

    return True


@CeleryExt.task()
def update_annotations(self: CeleryExt.TaskType):
    graph = neo4j.get_instance()

    """
MATCH (v:Variant) WHERE not v:ToBeUpdated WITH v LIMIT 250000 SET v:ToBeUpdated

    cypher = "MATCH (n:Variant) WHERE not v:ToBeUpdated SET n:ToBeUpdated"
    graph.cypher(cypher)
    cypher = "MATCH (n:Gene) SET n:ToBeUpdated"
    graph.cypher(cypher)
    """

    log.info("Updating probands...")
    # Determine probands in trios, to be excluded for frequency, issue #114
    graph.cypher("MATCH (d:Dataset) SET d.is_proband = false")
    cypher = """
MATCH
(d:Dataset)-[:IS_DESCRIBED_BY]->(proband:Phenotype),
(proband)-[:SON]->(father:Phenotype)<-[:IS_DESCRIBED_BY]-(:Dataset),
(proband)-[:SON]->(mother:Phenotype)<-[:IS_DESCRIBED_BY]-(:Dataset)
WHERE (father) <> (mother)
SET d.is_proband = true
"""
    graph.cypher(cypher)

    log.info("Caching datasets...")
    datasets: Dict[str, bool] = {}
    for d in graph.Dataset.nodes.all():
        datasets[d.uuid] = d.is_proband

    chunk = 0
    while True:
        chunk += 1
        log.info("Retrieving chunk number %d" % chunk)
        cypher = "MATCH (n:ToBeUpdated) WHERE n:Variant"
        # cypher += " RETURN id(n) as id LIMIT 50000"
        cypher += " RETURN n LIMIT 50000"
        results = graph.cypher(cypher)

        log.info("Updating chunk number %d" % chunk)

        count = 0
        for row in results:
            computeAlleleFrequency(graph, graph.Variant.inflate(row[0]), datasets)

            count += 1

        if count == 0:
            log.info("No more variants to be updated")
            break

    log.info("Everything is updated!")
    return "Everything is updated!"
