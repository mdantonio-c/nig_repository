from restapi.connectors import neo4j
from restapi.connectors.celery import CeleryExt
from restapi.utilities.logs import log


@CeleryExt.task()
def link_variants(self, phenotype_uuid=None):
    graph = neo4j.get_instance()
    if phenotype_uuid is None:
        phenotypes = graph.Phenotype.nodes.all()
    else:
        try:
            p = graph.Phenotype.nodes.get(uuid=phenotype_uuid)
            phenotypes = [p]
        except graph.Phenotype.DoesNotExist:
            return False

    for p in phenotypes:

        for v in p.confirmed_variant.all():
            p.confirmed_variant.disconnect(v)

        if not p.identified_genes:
            continue
        for variant in p.identified_genes:
            gene = variant["genename"]
            zygosity = variant.get("zygosity")
            ref = variant["reference"]
            alt = variant["alteration"]
            chr = variant["chromosome"]
            start = variant["start"]
            end = variant["end"]
            # genome = variant['genome']

            cypher = "MATCH (v:Variant)-[:LOCATED_IN]->(g:Gene)"
            cypher += " WHERE g.geneName =~ '(?i)%s'" % gene
            cypher += " AND v.chromosome = '%s'" % chr
            cypher += " AND v.start = %d" % start
            cypher += " AND v.end = %d" % end
            cypher += " AND v.ref = '%s'" % ref
            cypher += " AND v.alt = '%s'" % alt
            cypher += " MATCH (v)"
            cypher += "-[observed_variant:OBSERVED_IN]->(file:File)"
            cypher += "<-[:CONTAINS]-(dataset:Dataset)"
            cypher += "-[:IS_DESCRIBED_BY]->(phenotype:Phenotype)"
            cypher += " WHERE phenotype.uuid = '%s'" % p.uuid
            cypher += " RETURN v, observed_variant LIMIT 1"

            # log.critical(cypher)
            result = graph.cypher(cypher)
            found = False
            for row in result:
                v = graph.Variant.inflate(row[0])
                observed_variant = graph.VariantRelation.inflate(row[1])
                GT = observed_variant.GT
                A1 = GT[0:1]
                A2 = GT[2:3]
                hom = A1 == A2
                expected_hom = zygosity == "homozygous"

                # found = True
                if hom != expected_hom:
                    log.warning("Unexpected zygosity, cannot link variant to phenotype")
                elif not p.confirmed_variant.is_connected(v):
                    p.confirmed_variant.connect(v)
                    found = True
                else:
                    log.critical("Already connected")
            if found:
                log.info(
                    "Linked variant %s:%d-%d (%s>%s) to %s"
                    % (chr, start, end, ref, alt, p.uuid)
                )
            else:
                log.warning(
                    "Unable to link variant %s:%d-%d (%s>%s) to %s"
                    % (chr, start, end, ref, alt, p.uuid)
                )

    return True
