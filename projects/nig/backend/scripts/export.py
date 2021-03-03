import json
import time
from typing import Any, Dict

from neo4j.exceptions import AddressError
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


def cypher(query: str) -> Any:
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


def set_connection() -> None:
    try:
        params = {
            "user": "neo4j",
            "password": "chooseapassword",
            # "host": "repo.nig.cineca.it",
            "host": "130.186.13.16",
            "port": "7687",
        }
        uri = "bolt://{}:{}@{}:{}".format(
            params.get("user"),
            params.get("password"),
            params.get("host"),
            params.get("port"),
        )

        log.debug("Connected to %s" % uri)

        config.DATABASE_URL = uri
        # Ensure all DateTimes are provided with a timezone
        # before being serialised to UTC epoch
        config.FORCE_TIMEZONE = True  # default False

        db.url = uri
        db.set_connection(uri)
    except AddressError:
        log.error("Unable to connect, retrying in 5 seconds...")
        time.sleep(5)
        set_connection()


set_connection()

export_genes = True
variant_counter = 0

# export_genes = False
# variant_counter = 465

if export_genes:
    genes: Dict[str, Any] = {}
    log.debug("Reading genes")
    res = cypher("MATCH (g:Gene) return g")
    for r in res:
        gene = Gene.inflate(r[0])
        genes[gene.id] = {}

        for f in gene.__dict__.items():
            k = f[0]
            v = f[1]
            if k == "id":
                continue
            if k == "variants":
                continue
            genes[gene.id][k] = v

    f = "/media/sf_Data/export/export.genes.json"
    log.info("Exporting genes to %s" % f)
    with open(f, "w") as fp:
        json.dump(genes, fp)


limit = 10000
while True:
    variants: Dict[str, Any] = {}
    set_connection()
    skip = variant_counter * limit
    log.debug("Reading variants from {} to {}".format(skip + 1, skip + limit))
    res = cypher(
        "MATCH (v:Variant) return v ORDER by id(v) SKIP {} LIMIT {}".format(
            skip + 1, limit
        )
    )

    for r in res:
        variant = Variant.inflate(r[0])
        variants[variant.id] = {}
        for f in variant.__dict__.items():
            k = f[0]
            v = f[1]
            if k == "id":
                continue
            if k == "gene":
                v = None
                for g in variant.gene.all():
                    v = g.geneName
                if v is None:
                    continue
            # log.info("%s: %s" % (k, v))
            variants[variant.id][k] = v

        # log.info(variant.chromosome)
    if len(variants) == 0:
        log.info("No more variants found")
        break

    f = "/media/sf_Data/export/export.variants.%s.json" % variant_counter
    log.info("Exporting variants to %s" % f)
    with open(f, "w") as fp:
        json.dump(variants, fp)

    variant_counter += 1

    # if variant_counter > 0:
    #     break
# log.print(res)

# res = cypher(target_db, "MATCH (u:User) return u")
# log.print(res)

log.info("All completed")
