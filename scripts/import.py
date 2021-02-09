import json
import os

import neomodel
from neomodel import (  # StructuredRel,
    ArrayProperty,
    FloatProperty,
    IntegerProperty,
    RelationshipFrom,
    RelationshipTo,
    StringProperty,
    StructuredNode,
    ZeroOrMore,
    ZeroOrOne,
    config,
    db,
)
from restapi.utilities.logs import log

"""
docker run -t -d \
-v '/home/mdantonio/develop/export_db:/data' \
-p 7688:7687 \
-p 9090:7474 \
neo4j:3.4
"""

file_root = "/media/sf_Data/export4/export/"

params = {
    "user": "neo4j",
    "password": "NIG->Exported3",
    "host": "localhost",
    "port": "7688",
}

uri = "bolt://{}:{}@{}:{}".format(
    params.get("user"),
    params.get("password"),
    params.get("host"),
    params.get("port"),
)


def cypher(query):
    """ Execute normal neo4j queries """
    try:
        # results, meta = db.cypher_query(query)
        results, _ = db.cypher_query(query)
    except Exception as e:
        raise Exception("Failed to execute Cypher Query: {}\n{}".format(query, str(e)))
    # log.debug("Graph query.\nResults: %s\nMeta: %s" % (results, meta))
    return results


class Gene(StructuredNode):

    geneName = StringProperty(required=True, unique_index=True)

    CCDS_id = ArrayProperty()
    Disease_description = ArrayProperty()
    Entrez_gene_id = StringProperty()
    Essential_gene = StringProperty()
    Expression_GNF_Atlas = ArrayProperty()
    Expression_egenetics = ArrayProperty()
    GDI = FloatProperty()
    GO_biological_process = ArrayProperty()
    GO_cellular_component = ArrayProperty()
    GO_molecular_function = ArrayProperty()
    Gene_damage_prediction = StringProperty()
    Gene_full_name = StringProperty()
    Gene_old_names = ArrayProperty()
    Gene_other_names = ArrayProperty()
    Interactions_BioGRID = StringProperty()
    Interactions_ConsensusPathDB = StringProperty()
    Known_rec_info = StringProperty()
    MGI_mouse_gene = StringProperty()
    MGI_mouse_phenotype = ArrayProperty()
    MIM_disease = ArrayProperty()
    MIM_id = IntegerProperty()
    P_HI = FloatProperty()
    P_rec = FloatProperty()
    Pathway_BioCarta_short = StringProperty()
    Pathway_ConsensusPathDB = StringProperty()
    RVIS_ExAC_005 = FloatProperty()
    RVIS_ExAC_005_percentile = FloatProperty()
    Refseq_id = ArrayProperty()
    Tissue_specificity_uniprot = ArrayProperty()
    ZFIN_zebrafish_phenotype_gene = StringProperty()
    ZFIN_zebrafish_phenotype_quality = ArrayProperty()
    ZFIN_zebrafish_phenotype_structure = ArrayProperty()
    ZFIN_zebrafish_phenotype_tag = StringProperty()
    ucsc_id = StringProperty()

    variants = RelationshipFrom("Variant", "LOCATED_IN", cardinality=ZeroOrMore)


class Variant(StructuredNode):

    chromosome = StringProperty(required=True, index=True)
    start = IntegerProperty(required=True, index=True)
    end = IntegerProperty(required=True, index=True)
    ref = StringProperty(required=True, index=True)
    alt = StringProperty(required=True, index=True)
    variant_type = StringProperty(required=True, index=True)
    quality = FloatProperty(required=True)
    filt = StringProperty(required=True)

    dbSNP = ArrayProperty(index=True)

    total_allele = IntegerProperty()
    allele_count = IntegerProperty()
    allele_frequency = FloatProperty()
    num_hom = IntegerProperty()
    num_het = IntegerProperty()

    ANN = ArrayProperty()
    GENEINFO = StringProperty()
    LOF = ArrayProperty()
    NMD = ArrayProperty()
    CADD_phred = ArrayProperty()
    Feature_id = StringProperty()
    Impact = StringProperty()
    MainEffect = StringProperty(index=True)
    Var_aa_pos = StringProperty()
    Var_nt_pos = StringProperty()
    dbNSFP_Ancestral_allele = ArrayProperty()
    dbNSFP_ESP6500_AA_AF = ArrayProperty()
    dbNSFP_ESP6500_EA_AF = ArrayProperty()
    dbNSFP_Ensembl_geneid = ArrayProperty()
    dbNSFP_Ensembl_transcriptid = ArrayProperty()
    dbNSFP_ExAC_AC = ArrayProperty()
    dbNSFP_ExAC_AF = ArrayProperty()
    dbNSFP_ExAC_AFR_AC = ArrayProperty()
    dbNSFP_ExAC_AFR_AF = ArrayProperty()
    dbNSFP_ExAC_AMR_AC = ArrayProperty()
    dbNSFP_ExAC_AMR_AF = ArrayProperty()
    dbNSFP_ExAC_Adj_AC = ArrayProperty()
    dbNSFP_ExAC_Adj_AF = ArrayProperty()
    dbNSFP_ExAC_EAS_AC = ArrayProperty()
    dbNSFP_ExAC_EAS_AF = ArrayProperty()
    dbNSFP_ExAC_FIN_AC = ArrayProperty()
    dbNSFP_ExAC_FIN_AF = ArrayProperty()
    dbNSFP_ExAC_NFE_AC = ArrayProperty()
    dbNSFP_ExAC_NFE_AF = ArrayProperty()
    dbNSFP_ExAC_SAS_AC = ArrayProperty()
    dbNSFP_ExAC_SAS_AF = ArrayProperty()
    dbNSFP_FATHMM_pred = ArrayProperty()
    dbNSFP_GERP___RS = ArrayProperty()
    dbNSFP_Interpro_domain = ArrayProperty()
    dbNSFP_MetaLR_pred = ArrayProperty()
    dbNSFP_MetaSVM_pred = ArrayProperty()
    dbNSFP_MetaSVM_score = ArrayProperty()
    dbNSFP_Polyphen2_HDIV_pred = ArrayProperty()
    dbNSFP_Polyphen2_HVAR_pred = ArrayProperty()
    dbNSFP_Reliability_index = ArrayProperty()
    dbNSFP_SIFT_pred = ArrayProperty()
    dbNSFP_clinvar_trait = ArrayProperty()
    dbNSFP_clinvar_rs = ArrayProperty()
    dbNSFP_clinvar_clnsig = ArrayProperty()
    dbNSFP_aapos = ArrayProperty()
    dbSNP_GMAF = ArrayProperty()
    spidex_dpsi_zscore = StringProperty()

    gene = RelationshipTo("Gene", "LOCATED_IN", cardinality=ZeroOrOne)


log.debug("Connected to %s" % uri)

config.DATABASE_URL = uri
# Ensure all DateTimes are provided with a timezone
# before being serialised to UTC epoch
config.FORCE_TIMEZONE = True  # default False

db.url = uri
db.set_connection(uri)


create_genes = True
# create_genes = False

genes = {}
if create_genes:
    genes_file = os.path.join(file_root, "export.genes.json")
    log.info("Reading genes (%s)" % genes_file)
    with open(genes_file) as data_file:
        data = json.load(data_file)

    counter = 0
    for gid in data:

        attributes = data[gid]
        gene = Gene(**attributes)
        gene.save()
        genes[gene.geneName] = gene
        counter += 1
        if counter % 1000 == 0:
            log.info("Created %s genes" % counter)

else:
    log.info("Loading genes")

    res = cypher("MATCH (g:Gene) return g")
    for r in res:
        gene = Gene.inflate(r[0])
        genes[gene.geneName] = gene

variants_counter = 0
counter = 0
while True:
    variants_file = os.path.join(
        file_root, "export.variants.%s.json" % variants_counter
    )

    log.info("Reading file %s" % variants_file)

    variants_counter += 1
    if not os.path.isfile(variants_file):
        log.warning("%s not found, skipping file", variants_file)
        continue

    with open(variants_file) as data_file:
        data = None
        try:
            data = json.load(data_file)
        except json.decoder.JSONDecodeError as e:
            log.warning("Unable to read %s, skipping", variants_file)
            log.error(str(e))
            continue
        if data is None:
            continue

        if len(data) == 0:
            log.info("No more variants found")
            break

        for vid in data:
            attributes = data[vid]
            attributes["filt"] = attributes.pop("filter")
            geneName = attributes.pop("gene", None)
            if geneName is None:
                geneName = attributes.get("GENEINFO")
                if geneName is not None:
                    geneName = geneName.split(":")
                    geneName = geneName[0]

            variant = Variant(**attributes)
            variant.save()

            if geneName is None:
                gene = None
            elif geneName in genes:
                gene = genes[geneName]
            else:
                try:
                    gene = Gene.nodes.get(geneName=geneName)
                except neomodel.core.DoesNotExist:
                    # log.warning("%s not found, creating..." % geneName)
                    attributes = {"geneName": geneName}
                    gene = Gene(**attributes)
                    gene.save()
                genes[geneName] = gene

            if gene is not None:
                variant.gene.connect(gene)
            counter += 1
            if counter % 100000 == 0:
                log.info("Created %s variants" % counter)

log.info("All completed")
