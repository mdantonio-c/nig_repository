import ast
import time
from datetime import datetime

import pytz
from restapi.connectors.celery import CeleryExt
from restapi.utilities.logs import log


def count_alleles(datasets, probands):
    if datasets is None:
        return 0

    alleles = 0

    for d in datasets:
        is_proband = probands.get(d, False)
        if is_proband:
            continue
        alleles += 2

    return alleles


# def computeAlleleFrequency(self, node_id):
def computeAlleleFrequency(self, graph, variant, datasets):
    now = time.mktime(datetime.now(pytz.utc).timetuple())

    num_obs = count_alleles(variant.observed, datasets)
    num_nonobs = count_alleles(variant.non_observed, datasets)

    if num_obs == 0 and num_nonobs == 0:
        variant.total_allele = 0
        variant.allele_count = 0
        variant.allele_frequency = 0
        variant.save()
        return

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


def updateNodeModel(self, graph, data, oldModel, newModel, label):

    import neomodel

    node = oldModel.inflate(data)

    for f in dir(node):
        if f[0] == "_":
            continue
        attrAfter = getattr(newModel, f)
        attrBefore = getattr(oldModel, f)
        if (
            type(attrAfter) is neomodel.properties.ArrayProperty
            and type(attrBefore) is neomodel.properties.StringProperty
        ):

            oldvalue = getattr(node, f)
            if oldvalue is None:
                continue

            newvalue = ast.literal_eval(oldvalue)
            for k, v in enumerate(newvalue):
                if v is None:
                    newvalue[k] = "None"

            """
                We must ensure that the lists have the same types because
                in neo4j all values in the array must be of the same type.
                That means either all integers, all floats, all booleans
                or all strings. Mixing types is not currently supported.
                Storing empty arrays is only possible given certain conditions
            """
            if type(newvalue) is list:

                # Collect types of values in a set to remove duplicates
                types = {type(v) for v in newvalue}
                # If set contains more than a type, convert all to string
                if len(types) > 1:
                    for k, v in enumerate(newvalue):
                        newvalue[k] = "%s" % v

            cypher = "MATCH (n:ToBeUpdated)"
            cypher += " WHERE id(n) = %d" % node.id
            cypher += f" SET n.{f} = {newvalue}"
            graph.cypher(cypher)

    now = time.mktime(datetime.now(pytz.utc).timetuple())
    cypher = "MATCH (n:ToBeUpdated)"
    cypher += " WHERE id(n) = %d" % node.id
    cypher += " SET n.modified = %f" % now
    cypher += " REMOVE n:ToBeUpdated"
    graph.cypher(cypher)
    log.info("%s updated: %d" % (label, node.id))


@CeleryExt.task(name="update_annotations")
def update_annotations(self):
    graph = CeleryExt.app.get_service("neo4j")

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
    datasets = {}
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
            # computeAlleleFrequency(self, int(row[0]))
            computeAlleleFrequency(self, graph, graph.Variant.inflate(row[0]), datasets)

            count += 1

        if count == 0:
            log.info("No more variants to be updated")
            break

    log.info("Everything is updated!")
    return "Everything is updated!"
