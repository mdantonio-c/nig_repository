from neomodel import (  # UniqueIdProperty
    ArrayProperty,
    BooleanProperty,
    DateTimeProperty,
    FloatProperty,
    IntegerProperty,
    JSONProperty,
    RelationshipFrom,
    RelationshipTo,
    StringProperty,
    StructuredNode,
    StructuredRel,
    ZeroOrMore,
    ZeroOrOne,
)
from restapi.connectors.neo4j.types import IdentifiedNode, TimestampedNode


class UserCustom(IdentifiedNode):
    __abstract_node__ = True

    study_ownership = RelationshipFrom("Study", "IS_OWNED_BY", cardinality=ZeroOrMore)
    dataset_ownership = RelationshipFrom(
        "Dataset", "IS_OWNED_BY", cardinality=ZeroOrMore
    )


class Study(TimestampedNode):
    name = StringProperty(required=True)
    description = StringProperty(required=True)

    ownership = RelationshipTo(
        "restapi.connectors.neo4j.models.User", "IS_OWNED_BY", cardinality=ZeroOrMore
    )

    phenotypes = RelationshipFrom("Phenotype", "DEFINED_IN", cardinality=ZeroOrMore)
    technicals = RelationshipFrom(
        "TechnicalMetadata", "DEFINED_IN", cardinality=ZeroOrMore
    )
    resources = RelationshipFrom("Resource", "CONTAINED_IN", cardinality=ZeroOrMore)

    datasets = RelationshipTo("Dataset", "CONTAINS", cardinality=ZeroOrMore)
    linked_datasets = RelationshipTo("Dataset", "IS_LINKED", cardinality=ZeroOrMore)


class Dataset(TimestampedNode):
    name = StringProperty(required=True)
    # unique_name = StringProperty(required=True, unique_index=True)
    description = StringProperty()
    is_proband = BooleanProperty()

    ownership = RelationshipTo(
        "restapi.connectors.neo4j.models.User", "IS_OWNED_BY", cardinality=ZeroOrMore
    )
    parent_study = RelationshipFrom("Study", "CONTAINS", cardinality=ZeroOrMore)
    linked_studies = RelationshipFrom("Study", "IS_LINKED", cardinality=ZeroOrMore)
    files = RelationshipTo("File", "CONTAINS", cardinality=ZeroOrMore)
    virtualfiles = RelationshipTo("VirtualFile", "CONTAINS", cardinality=ZeroOrMore)
    phenotype = RelationshipTo("Phenotype", "IS_DESCRIBED_BY", cardinality=ZeroOrOne)
    technical = RelationshipTo(
        "TechnicalMetadata", "IS_DESCRIBED_BY", cardinality=ZeroOrOne
    )


class VariantRelation(StructuredRel):
    quality = FloatProperty()
    heterozygosity = FloatProperty()
    num_alt = IntegerProperty()
    allele_num = IntegerProperty()

    # GENOTYPING
    GT = StringProperty()
    AD = StringProperty()
    DP = StringProperty()
    GQ = StringProperty()
    PL = StringProperty()
    TP = StringProperty()
    PGT = StringProperty()
    PID = StringProperty()

    # ANNOTATIONS
    AC = StringProperty()
    AF = FloatProperty()
    AN = IntegerProperty()
    BaseQRankSum = StringProperty()
    ClippingRankSum = FloatProperty()
    DP = IntegerProperty()
    DS = StringProperty()
    Dels = StringProperty()
    END = StringProperty()
    ExcessHet = FloatProperty()
    FS = FloatProperty()
    HaplotypeScore = StringProperty()
    InbreedingCoeff = StringProperty()
    MLEAC = IntegerProperty()
    MLEAF = FloatProperty()
    MQ = FloatProperty()
    MQ0 = IntegerProperty()
    MQRankSum = FloatProperty()
    QD = FloatProperty()
    RAW_MQ = StringProperty()
    ReadPosRankSum = FloatProperty()
    SOR = FloatProperty()


class File(IdentifiedNode):
    name = StringProperty(required=True)
    type = StringProperty()
    size = IntegerProperty()
    status = StringProperty()
    task_id = StringProperty()
    metadata = JSONProperty()

    dataset = RelationshipFrom("Dataset", "CONTAINS", cardinality=ZeroOrMore)

    has_variant = RelationshipFrom(
        "Variant", "OBSERVED_IN", cardinality=ZeroOrMore, model=VariantRelation
    )

    has_not_variant = RelationshipFrom(
        "Variant", "NOT_OBSERVED_IN", cardinality=ZeroOrMore, model=VariantRelation
    )


class VirtualFile(IdentifiedNode):
    name = StringProperty(required=True)
    info = StringProperty(required=True)

    dataset = RelationshipFrom("Dataset", "CONTAINS", cardinality=ZeroOrMore)

    has_variant = RelationshipFrom(
        "Variant", "OBSERVED_IN", cardinality=ZeroOrMore, model=VariantRelation
    )

    has_not_variant = RelationshipFrom(
        "Variant", "NOT_OBSERVED_IN", cardinality=ZeroOrMore, model=VariantRelation
    )

    from_resource = RelationshipTo("Resource", "FROM", cardinality=ZeroOrOne)


class Phenotype(TimestampedNode):
    name = StringProperty(required=True, is_restricted=True)
    birthday = DateTimeProperty()
    deathday = DateTimeProperty()
    sex = StringProperty(required=True)

    identified_genes = JSONProperty(is_restricted=True)

    defined_in = RelationshipTo("Study", "DEFINED_IN", cardinality=ZeroOrMore)
    describe = RelationshipFrom("Dataset", "IS_DESCRIBED_BY", cardinality=ZeroOrOne)
    birth_place = RelationshipTo("GeoData", "BIRTH_PLACE", cardinality=ZeroOrOne)
    confirmed_variant = RelationshipFrom("Variant", "CONFIRMED_IN")
    son = RelationshipTo("Phenotype", "SON", cardinality=ZeroOrMore)
    father = RelationshipTo("Phenotype", "FATHER", cardinality=ZeroOrMore)
    mother = RelationshipTo("Phenotype", "MOTHER", cardinality=ZeroOrMore)
    hpo = RelationshipTo("HPO", "DESCRIBED_BY", cardinality=ZeroOrMore)


class TechnicalMetadata(TimestampedNode):
    name = StringProperty(required=True)
    sequencing_date = DateTimeProperty()
    platform = StringProperty()
    enrichment_kit = StringProperty()

    defined_in = RelationshipTo("Study", "DEFINED_IN", cardinality=ZeroOrMore)
    describe = RelationshipFrom("Dataset", "IS_DESCRIBED_BY", cardinality=ZeroOrOne)


# Properties copied from File
class Resource(TimestampedNode):
    name = StringProperty(required=True)
    type = StringProperty()

    size = IntegerProperty()
    status = StringProperty()
    task_id = StringProperty()
    metadata = JSONProperty()
    study = RelationshipTo("Study", "CONTAINED_IN", cardinality=ZeroOrMore)

    virtual_file = RelationshipFrom("VirtualFile", "FROM", cardinality=ZeroOrMore)


class Gene(TimestampedNode):

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


class Variant(TimestampedNode):

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

    observed = JSONProperty()
    non_observed = JSONProperty()

    gene = RelationshipTo("Gene", "LOCATED_IN", cardinality=ZeroOrOne)

    extracted_from = RelationshipTo(
        "File", "OBSERVED_IN", cardinality=ZeroOrOne, model=VariantRelation
    )

    virtual_extracted_from = RelationshipTo(
        "VirtualFile", "OBSERVED_IN", cardinality=ZeroOrOne, model=VariantRelation
    )

    not_extracted_from = RelationshipTo(
        "File", "NOT_OBSERVED_IN", cardinality=ZeroOrOne, model=VariantRelation
    )

    virtual_not_extracted_from = RelationshipTo(
        "VirtualFile", "NOT_OBSERVED_IN", cardinality=ZeroOrOne, model=VariantRelation
    )

    confirmed_in = RelationshipTo("Phenotype", "CONFIRMED_IN")


class GeoData(IdentifiedNode):

    country = StringProperty(required=True)
    macroarea = StringProperty()
    region = StringProperty(required=True)
    province = StringProperty(required=True)
    city = StringProperty(required=True)
    latitude = FloatProperty()
    longitude = FloatProperty()
    population = IntegerProperty()

    birth_place = RelationshipFrom("Phenotype", "BIRTH_PLACE", cardinality=ZeroOrMore)


class HPO(StructuredNode):

    hpo_id = StringProperty(required=True, unique_index=True)
    label = StringProperty(required=True)
    description = StringProperty(required=True, nullable=True)
    synonyms = StringProperty()
    translation = StringProperty()

    is_cluster_node = IntegerProperty()
    hide_node = BooleanProperty(default=False)

    phenotypes = RelationshipFrom("Phenotype", "DESCRIBED_BY", cardinality=ZeroOrMore)

    generalized_parent = RelationshipTo("HPO", "GENERALIZED_BY")
    specification_child = RelationshipFrom("HPO", "GENERALIZED_BY")

    parent = RelationshipFrom("HPO", "IS_CHILD_OF")
    children = RelationshipTo("HPO", "IS_CHILD_OF")
