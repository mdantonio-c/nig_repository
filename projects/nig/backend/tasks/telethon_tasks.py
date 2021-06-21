# import json
# import os
# import re
# from datetime import datetime

# import dateutil.parser
# import pytz
# from celery.result import AsyncResult
# from nig.endpoints import NIGEndpoint
# from restapi.utilities.logs import log

# FILE_TYPE = "File"
# RESOURCE_TYPE = "Resource"
# GENEM = "GENE METADATA"
# FUNCM = "FUNCTIONAL METADATA"
# TECHM = "TECHNICAL METADATA"
# SKIPM = "SKIP METADATA"

####################
# Define your celery tasks

# @after_task_publish.connect
# def update_sent_state(sender=None, body=None, **kwargs):
#     task = AsyncResult(body['id'])
#     task.backend.store_result(task.id, None, 'SENT')
#     log.critical("Setting status 'SENT' to task %s " % task.id)


# def export(export_counter, variants):
#     f = "/uploads/export/export.variants.%s.json" % export_counter
#     log.info("Exporting variants to %s" % f)
#     with open(f, "w+") as fp:
#         json.dump(variants, fp)


# def export_genes(genes):
#     f = "/uploads/export/export.genes.json"
#     log.info("Exporting genes to %s" % f)
#     with open(f, "w+") as fp:
#         json.dump(genes, fp)


# def count_alleles(datasets, probands):
#     if datasets is None:
#         return 0

#     alleles = 0

#     for d in datasets:
#         is_proband = probands.get(d, False)
#         if is_proband:
#             # log.info("Skipping variant because %s is proband", d)
#             continue
#         alleles += 2

#     return alleles


# def progress(self, state, uuid):
#     if uuid is not None:
#         log.info(f"{state} [{uuid}]")
#     self.update_state(state=state)


"""
@CeleryExt.task()
def import_file(
    self,
    uuid,
    stage_path,
    abs_file,
    type="File",
    tmp_name=None,
    irods_user=None,
    irods_group=None,
    data_path=None,
):

    progress(self, "Starting import", uuid)

    if stage_path is not None:
        stage_path = stage_path.replace("//", "/")
        progress(self, "Reading file from %s", stage_path)

    graph = neo4j.get_instance()
    from undefined.connectors import irods

    icom = irods.get_instance()

    fromDisk = tmp_name is not None
    reimport = data_path is not None
    try:

        if type == FILE_TYPE:
            model = graph.File
        elif type == RESOURCE_TYPE:
            model = graph.Resource
        else:
            model = None

        self.type = type
        self.fileNode = model.nodes.get(uuid=uuid)

        # METADATA EXTRACTION
        filename, file_extension = os.path.splitext(abs_file)
        unused, file_sub_extension = os.path.splitext(filename)

        if file_extension.startswith("."):
            file_extension = file_extension[1:]

        if file_sub_extension.startswith("."):
            file_sub_extension = file_sub_extension[1:]

        file_type = file_extension
        fastq = ["fastq", "fq"]
        vcf = ["vcf"]
        ped = ["ped", "pedigree"]
        tech = ["tech", "technical"]
        parser = None
        if file_extension in fastq:
            parser = parse_file_fastq
            file_type = "fastq"
        elif file_extension in vcf:
            if file_sub_extension == "g":
                file_type = "gvcf"
            else:
                parser = parse_file_vcf
                file_type = "vcf"
        elif file_extension in ped:
            parser = parse_file_ped
            file_type = "ped"
        elif file_extension in tech:
            parser = parse_file_tech
            file_type = "tech"

        if parser is None:
            metadata = {}
        else:
            # IRODS -> LOCAL/TMP
            progress(self, "Reading file", uuid)

            if not fromDisk:
                # mah!
                # from utilities.random import get_random_name

                # tmp_name = "/tmp/%s" % get_random_name(lenght=48, prefix="TMP_")
                tmp_name = "/tmp/get_random_name_not_implemented"
                if stage_path is not None:
                    icom.open(stage_path, tmp_name)
                    log.info("copy from %s to %s", stage_path, tmp_name)
                elif data_path is not None:
                    icom.open(data_path, tmp_name)
                    log.info("copy from %s to %s", data_path, tmp_name)

            progress(self, "Extracting metadata", uuid)
            metadata = parser(self, graph, tmp_name, reimport=reimport)
            st = os.stat(tmp_name)
            self.fileNode.size = st.st_size

        # SAVE METADATA
        self.fileNode.status = "completed"
        self.fileNode.metadata = metadata
        self.fileNode.type = file_type
        self.fileNode.save()

        if fromDisk:
            # TMP DISK -> IRODS DATA
            progress(self, "Importing file from tmp disk", uuid)
            icom.save(tmp_name, destination=abs_file, force=True)

        elif stage_path is not None:
            # IRODS STAGE -> IRODS DATA
            progress(self, "Importing file from stage", uuid)
            icom.copy(stage_path, abs_file, force=True)
            # RM FROM IRODS STAGE
            progress(self, "Removing file from stage", uuid)
            icom.remove(stage_path, recursive=True)

        if irods_user is not None:
            icom.set_permissions(abs_file, "read", irods_user, recursive=False)

        if irods_group is not None:
            for g in irods_group:
                icom.set_permissions(abs_file, "read", g, recursive=False)

        if tmp_name is not None:
            # REMOVE LOCAL/TMP
            progress(self, "Removing temporary files", uuid)
            os.remove(tmp_name)

        progress(self, "Completed", uuid)

    except graph.File.DoesNotExist:
        progress(self, "Import error", None)
        log.error("Task error, uuid %s not found" % uuid)

    return 1


def parse_file_fastq(self, graph, filename, reimport=False):

    # Just a test with Spark:
    # from pyspark import SparkConf, SparkContext
    # # configuration with all defaults
    # conf = SparkConf()
    # # spark context based on our configuration
    # sc = SparkContext(conf=conf)
    # # to hide warnings like:
    # # NativeCodeLoader: Unable to load native-hadoop library \
    # #     for your platform... using builtin-java classes where applicable
    # import logging
    # sc.setLogLevel(logging.ERROR)

    # rdd = sc.textFile(filename)
    # metadata = dict()

    # metadata["num_reads"] = rdd.count() / 4
    # return metadata

    # END OF SPARK TEST

    metadata = dict()
    lens = list()

    with open(filename) as f:
        while True:
            # header = f.readline()
            f.readline()
            read = f.readline()
            # line3 = f.readline()
            f.readline()
            quality = f.readline()

            if not quality:
                break

            lens.append(len(read))

    metadata["num_reads"] = len(lens)
    # metadata["mean_len"] = statistics.mean(lens)
    # metadata["median_len"] = statistics.median(lens)
    # metadata["min_len"] = min(lens)
    # metadata["max_len"] = max(lens)
    # metadata["std_len"] = statistics.stdev(lens)

    return metadata


def getParent(self, graph, study, name, relation, son):
    if name == "0":
        return None

    rel = f"({name})-[{relation}]->({son})"
    u_name = NIGEndpoint.createUniqueIndex(study.uuid, name)
    try:
        return graph.Phenotype.nodes.get(unique_name=u_name)
    except graph.Phenotype.DoesNotExist:
        log.error(f"Unable to create {rel}, {name} not found")
        return None


def get_value(key, header, line):
    if header is None:
        return None
    if key not in header:
        return None
    index = header.index(key)
    if index >= len(line):
        return None
    value = line[index]
    if value is None:
        return None
    if value == "":
        return None
    if value == "-":
        return None
    if value == "N/A":
        return None
    return value


def date_from_string(date: str, fmt: str = "%d/%m/%Y") -> datetime:

    if date == "":
        return ""
    # datetime.now(pytz.utc)
    try:
        return_date = datetime.strptime(date, fmt)
    except BaseException:
        return_date = dateutil.parser.parse(date)

    # TODO: test me with: 2017-09-22T07:10:35.822772835Z
    if return_date.tzinfo is None:
        return pytz.utc.localize(return_date)

    return return_date


def parse_file_ped(self, graph, filename, reimport=False):
    log.info("PED PARSER: %s", filename)
    if not os.path.isfile(filename):
        log.error("ped file not found: %s", filename)
        return False

    with open(filename) as f:

        header = None
        while True:
            row = f.readline()
            if not row:
                break

            if row.startswith("#"):
                # Remove the initial #
                row = row[1:].strip().lower()
                # header = re.split(r"\\s+|\t", line)
                header = re.split(r"\t", row)
                continue

            row = row.strip()
            # line = re.split(r"\\s+|\t", line)
            line = re.split(r"\t", row)

            if len(line) < 5:
                continue

            # pedigree_id = line[0]
            individual_id = line[1]
            father = line[2]
            mother = line[3]
            sex = line[4]

            study = self.fileNode.study.all().pop(0)
            log.info("Retrieved study: %s", study.uuid)

            unique_name = NIGEndpoint.createUniqueIndex(study.uuid, individual_id)

            log.info("Assigned unique name: %s", unique_name)

            # Verify if this phenotype already exists
            try:
                graph.Phenotype.nodes.get(unique_name=unique_name)
                log.warning(
                    "Phenotype %s already exists in %s, skipping it"
                    % (individual_id, study.uuid)
                )
                continue
            except graph.Phenotype.DoesNotExist:
                pass

            if sex == "1":
                sex = "male"
            elif sex == "2":
                sex = "female"

            properties = {}
            properties["name"] = individual_id
            properties["unique_name"] = unique_name
            properties["sex"] = sex

            value = get_value("birthday", header, line)
            if value is not None:
                properties["birthday"] = date_from_string(value)

            value = get_value("deathday", header, line)
            if value is not None:
                properties["deathday"] = date_from_string(value)

            log.info(f"Creating {individual_id} with sex = {sex}")
            phenotype = graph.Phenotype(**properties).save()

            phenotype.defined_in.connect(study)

            father_node = getParent(self, graph, study, father, "father", individual_id)

            mother_node = getParent(self, graph, study, mother, "mother", individual_id)

            if father_node is not None:
                phenotype.son.connect(father_node)
                father_node.father.connect(phenotype)

            if mother_node is not None:
                phenotype.son.connect(mother_node)
                mother_node.mother.connect(phenotype)

            value = get_value("birthplace", header, line)
            if value is not None:

                value = graph.sanitize_input(value)
                cypher = "MATCH (geo:GeoData)"
                cypher += " WHERE geo.city =~ '(?i)%s'" % value
                cypher += " RETURN geo LIMIT 1"
                results = graph.cypher(cypher)
                geo = None
                for row in results:
                    geo = graph.GeoData.inflate(row[0])
                    break

                if geo is None:
                    log.warning("GeoData not found for city=[%s]" % value)
                else:
                    phenotype.birth_place.connect(geo)

                # try:
                #     geo = graph.GeoData.nodes.get(city=value)
                # except graph.GeoData.DoesNotExist:
                # pass

            value = get_value("hpo", header, line)
            if value is not None:
                hpo_list = value.split(",")
                for hpo_id in hpo_list:
                    try:
                        hpo = graph.HPO.nodes.get(hpo_id=hpo_id)
                        phenotype.hpo.connect(hpo)
                    except graph.HPO.DoesNotExist:
                        pass

            value = get_value("dataset", header, line)
            if value is not None:
                dataset_list = value.split(",")
                for dataset_name in dataset_list:
                    for dataset in study.datasets.all():
                        if dataset.name == dataset_name:
                            try:
                                phenotype.describe.connect(dataset)
                            except BaseException:
                                log.warning(
                                    "Unble to connect %s to %s"
                                    % (phenotype.uuid, dataset.uuid)
                                )


def parse_file_tech(self, graph, filename, reimport=False):
    log.info("TECH PARSER: %s", filename)
    if not os.path.isfile(filename):
        log.error("tech file not found: %s", filename)
        return False
    with open(filename) as f:

        header = None
        while True:
            row = f.readline()
            if not row:
                break

            if row.startswith("#"):
                # Remove the initial #
                row = row[1:].strip().lower()
                # header = re.split(r"\\s+|\t", row)
                header = re.split(r"\t", row)
                continue

            row = row.strip()
            # line = re.split(r"\\s+|\t", row)
            line = re.split(r"\t", row)

            if len(line) < 4:
                continue

            name = line[0]
            date = line[1]
            platform = line[2]
            kit = line[3]

            study = self.fileNode.study.all().pop(0)
            log.info("Retrieved study: %s", study.uuid)

            unique_name = NIGEndpoint.createUniqueIndex(study.uuid, name)
            log.info("Assigned unique name: %s", unique_name)

            # Verify if this technical already exists
            try:
                graph.TechnicalMetadata.nodes.get(unique_name=unique_name)
                log.warning(
                    "Technical %s already exists in %s, skipping it"
                    % (name, study.uuid)
                )
                continue
            except graph.TechnicalMetadata.DoesNotExist:
                pass

            properties = {}
            properties["name"] = name
            properties["unique_name"] = unique_name
            properties["sequencing_date"] = date_from_string(date)
            properties["platform"] = platform
            properties["enrichment_kit"] = kit

            log.info("Creating technical: %s" % (name))
            technical = graph.TechnicalMetadata(**properties).save()
            technical.defined_in.connect(study)

            value = get_value("dataset", header, line)
            if value is not None:
                dataset_list = value.split(",")
                for dataset_name in dataset_list:
                    for dataset in study.datasets.all():
                        if dataset.name == dataset_name:
                            try:
                                technical.describe.connect(dataset)
                            except BaseException:
                                log.warning(
                                    "Unble to connect %s to %s"
                                    % (technical.uuid, dataset.uuid)
                                )


def parse_file_vcf(self, graph, vcf_file, reimport=False):

    from restapi.services.neo4j.models import ArrayProperty

    # import py2neo

    fConf = {}

    fConf["RECURRENCE_IN_OUR_DB"] = {"type": SKIPM}
    fConf["DDG2P"] = {"type": SKIPM}
    fConf["Mendel"] = {"type": SKIPM}
    fConf["secondaryEff"] = {"type": SKIPM}
    fConf["ACMG"] = {"type": SKIPM}
    fConf["DB"] = {"type": SKIPM}
    fConf["dbNSFP_rf_score"] = {"type": SKIPM}
    fConf["dbNSFP_ada_score"] = {"type": SKIPM}
    fConf["PHEN"] = {"type": SKIPM}
    fConf["dbNSFP_1000Gp3_AC"] = {"type": SKIPM}
    fConf["dbNSFP_1000Gp3_AF"] = {"type": SKIPM}
    fConf["dbNSFP_ALSPAC_AC"] = {"type": SKIPM}
    fConf["dbNSFP_ALSPAC_AF"] = {"type": SKIPM}
    fConf["dbNSFP_CADD_phred"] = {"type": SKIPM}
    fConf["dbNSFP_DANN_rankscore"] = {"type": SKIPM}
    fConf["dbNSFP_DANN_score"] = {"type": SKIPM}
    fConf["dbNSFP_ESP6500_AA_AC"] = {"type": SKIPM}
    fConf["dbNSFP_ESP6500_EA_AC"] = {"type": SKIPM}
    fConf["dbNSFP_Eigen_PC_raw_rankscore"] = {"type": SKIPM}
    fConf["dbNSFP_Eigen_raw"] = {"type": SKIPM}
    fConf["dbNSFP_Eigen_raw_rankscore"] = {"type": SKIPM}
    fConf["dbNSFP_TWINSUK_AC"] = {"type": SKIPM}
    fConf["dbNSFP_TWINSUK_AF"] = {"type": SKIPM}
    fConf["dbNSFP_fathmm_MKL_coding_pred"] = {"type": SKIPM}
    fConf["dbNSFP_integrated_confidence_value"] = {"type": SKIPM}
    fConf["dbNSFP_integrated_fitCons_score"] = {"type": SKIPM}
    fConf["DANN_score"] = {"type": SKIPM}
    fConf["SPIDEX_dpsi_zscore"] = {"type": SKIPM}
    fConf["TWINSUK_AF.indel"] = {"type": SKIPM}
    fConf["DANN_rank_score"] = {"type": SKIPM}
    fConf["TWINSUK_AF.snp"] = {"type": SKIPM}
    fConf["phyloP100way_vertebrate_rankscore"] = {"type": SKIPM}
    fConf["1000Gp3_AF.indel"] = {"type": SKIPM}
    fConf["CADD_raw"] = {"type": SKIPM}
    fConf["phyloP100way_vertebrate"] = {"type": SKIPM}
    fConf["phastCons100way_vertebrate_rankscore"] = {"type": SKIPM}
    fConf["phastCons100way_vertebrate"] = {"type": SKIPM}
    fConf["ExAC_nonTCGA_AF.indel"] = {"type": SKIPM}
    fConf["dbNSFP_MetaLR_score"] = {"type": SKIPM}
    fConf["dbNSFP_PROVEAN_pred"] = {"type": SKIPM}
    fConf["dbNSFP_PROVEAN_score"] = {"type": SKIPM}
    fConf["dbNSFP_Polyphen2_HDIV_score"] = {"type": SKIPM}
    fConf["dbNSFP_Polyphen2_HVAR_score"] = {"type": SKIPM}
    fConf["dbNSFP_SIFT_score"] = {"type": SKIPM}
    fConf["dbNSFP_VEST3_score"] = {"type": SKIPM}
    fConf["ExAC_AF.indel"] = {"type": SKIPM}
    fConf["fathmm-MKL_non-coding_score"] = {"type": SKIPM}
    fConf["fathmm-MKL_coding_score"] = {"type": SKIPM}
    fConf["ESP6500_EA_AF.indels"] = {"type": SKIPM}
    fConf["ESP6500_EA_AF.snps"] = {"type": SKIPM}
    fConf["NEGATIVE_TRAIN_SITE"] = {"type": SKIPM}
    fConf["POSITIVE_TRAIN_SITE"] = {"type": SKIPM}
    fConf["VQSLOD"] = {"type": SKIPM}
    fConf["culprit"] = {"type": SKIPM}
    fConf["integrated_fitCons_score"] = {"type": SKIPM}
    fConf["ASP"] = {"type": SKIPM}
    fConf["ASS"] = {"type": SKIPM}
    fConf["CAF"] = {"type": SKIPM}
    fConf["COMMON"] = {"type": SKIPM}
    fConf["DSS"] = {"type": SKIPM}
    fConf["G5"] = {"type": SKIPM}
    fConf["G5A"] = {"type": SKIPM}
    fConf["GNO"] = {"type": SKIPM}
    fConf["HD"] = {"type": SKIPM}
    fConf["INT"] = {"type": SKIPM}
    fConf["KGPhase1"] = {"type": SKIPM}
    fConf["KGPhase3"] = {"type": SKIPM}
    fConf["LSD"] = {"type": SKIPM}
    fConf["MTP"] = {"type": SKIPM}
    fConf["NOC"] = {"type": SKIPM}
    fConf["NOV"] = {"type": SKIPM}
    fConf["NSF"] = {"type": SKIPM}
    fConf["NSM"] = {"type": SKIPM}
    fConf["NSN"] = {"type": SKIPM}
    fConf["OM"] = {"type": SKIPM}
    fConf["OTH"] = {"type": SKIPM}
    fConf["PM"] = {"type": SKIPM}
    fConf["PMC"] = {"type": SKIPM}
    fConf["R3"] = {"type": SKIPM}
    fConf["R5"] = {"type": SKIPM}
    fConf["REF"] = {"type": SKIPM}
    fConf["RS"] = {"type": SKIPM}
    fConf["RSPOS"] = {"type": SKIPM}
    fConf["RV"] = {"type": SKIPM}
    fConf["S3D"] = {"type": SKIPM}
    fConf["SAO"] = {"type": SKIPM}
    fConf["SLO"] = {"type": SKIPM}
    fConf["SSR"] = {"type": SKIPM}
    fConf["SYN"] = {"type": SKIPM}
    fConf["TPA"] = {"type": SKIPM}
    fConf["U3"] = {"type": SKIPM}
    fConf["U5"] = {"type": SKIPM}
    fConf["VC"] = {"type": SKIPM}
    fConf["VLD"] = {"type": SKIPM}
    fConf["VP"] = {"type": SKIPM}
    fConf["WGT"] = {"type": SKIPM}
    fConf["dbSNPBuildID"] = {"type": SKIPM}

    fConf["CCDS_id"] = {"type": GENEM, "field": "CCDS_id"}
    fConf["Disease_description"] = {"type": GENEM, "field": "Disease_description"}
    fConf["Entrez_gene_id"] = {"type": GENEM, "field": "Entrez_gene_id"}
    fConf["Essential_gene"] = {"type": GENEM, "field": "Essential_gene"}
    fConf["Expression(GNF/Atlas)"] = {"type": GENEM, "field": "Expression_GNF_Atlas"}
    fConf["Expression(egenetics)"] = {"type": GENEM, "field": "Expression_egenetics"}
    fConf["GDI"] = {"type": GENEM, "field": "GDI"}
    fConf["GO_biological_process"] = {"type": GENEM, "field": "GO_biological_process"}
    fConf["GO_cellular_component"] = {"type": GENEM, "field": "GO_cellular_component"}
    fConf["GO_molecular_function"] = {"type": GENEM, "field": "GO_molecular_function"}
    fConf["Gene_damage_prediction"] = {"type": GENEM, "field": "Gene_damage_prediction"}
    fConf["Gene_full_name"] = {"type": GENEM, "field": "Gene_full_name"}
    fConf["Gene_old_names"] = {"type": GENEM, "field": "Gene_old_names"}
    fConf["Gene_other_names"] = {"type": GENEM, "field": "Gene_other_names"}
    fConf["Interactions(BioGRID)"] = {"type": GENEM, "field": "Interactions_BioGRID"}
    fConf["Interactions(ConsensusPathDB)"] = {
        "type": GENEM,
        "field": "Interactions_ConsensusPathDB",
    }
    fConf["Known_rec_info"] = {"type": GENEM, "field": "Known_rec_info"}
    fConf["MGI_mouse_gene"] = {"type": GENEM, "field": "MGI_mouse_gene"}
    fConf["MGI_mouse_phenotype"] = {"type": GENEM, "field": "MGI_mouse_phenotype"}
    fConf["MIM_disease"] = {"type": GENEM, "field": "MIM_disease"}
    fConf["MIM_id"] = {"type": GENEM, "field": "MIM_id"}
    fConf["P(HI)"] = {"type": GENEM, "field": "P_HI"}
    fConf["P(rec)"] = {"type": GENEM, "field": "P_rec"}
    fConf["Pathway(BioCarta)_short"] = {
        "type": GENEM,
        "field": "Pathway_BioCarta_short",
    }
    fConf["Pathway(ConsensusPathDB)"] = {
        "type": GENEM,
        "field": "Pathway_ConsensusPathDB",
    }
    fConf["RVIS_ExAC_0.05"] = {"type": GENEM, "field": "RVIS_ExAC_005"}
    fConf["RVIS_ExAC_0.05_percentile"] = {
        "type": GENEM,
        "field": "RVIS_ExAC_005_percentile",
    }
    fConf["Refseq_id"] = {"type": GENEM, "field": "Refseq_id"}
    fConf["Tissue_specificity(uniprot)"] = {
        "type": GENEM,
        "field": "Tissue_specificity_uniprot",
    }
    fConf["ZFIN_zebrafish_phenotype_gene"] = {
        "type": GENEM,
        "field": "ZFIN_zebrafish_phenotype_gene",
    }
    fConf["ZFIN_zebrafish_phenotype_quality"] = {
        "type": GENEM,
        "field": "ZFIN_zebrafish_phenotype_quality",
    }
    fConf["ZFIN_zebrafish_phenotype_structure"] = {
        "type": GENEM,
        "field": "ZFIN_zebrafish_phenotype_structure",
    }
    fConf["ZFIN_zebrafish_phenotype_tag"] = {
        "type": GENEM,
        "field": "ZFIN_zebrafish_phenotype_tag",
    }
    fConf["geneName"] = {"type": GENEM, "field": "geneName"}
    fConf["ucsc_id"] = {"type": GENEM, "field": "ucsc_id"}

    fConf["ANN"] = {"type": FUNCM, "field": "ANN"}
    fConf["GENEINFO"] = {"type": FUNCM, "field": "GENEINFO"}
    # Temporary skipping ANN
    # fConf['ANN'] = {"type": SKIPM}
    # fConf['GENEINFO'] = {"type": SKIPM}

    fConf["LOF"] = {"type": FUNCM, "field": "LOF"}
    fConf["NMD"] = {"type": FUNCM, "field": "NMD"}
    fConf["CADD_phred"] = {"type": FUNCM, "field": "CADD_phred"}
    fConf["Feature_id"] = {"type": FUNCM, "field": "Feature_id"}
    fConf["Impact"] = {"type": FUNCM, "field": "Impact"}
    fConf["MainEffect"] = {"type": FUNCM, "field": "MainEffect"}
    fConf["Var_aa_pos"] = {"type": FUNCM, "field": "Var_aa_pos"}
    fConf["Var_nt_pos"] = {"type": FUNCM, "field": "Var_nt_pos"}
    fConf["dbNSFP_Ancestral_allele"] = {
        "type": FUNCM,
        "field": "dbNSFP_Ancestral_allele",
    }
    fConf["dbNSFP_ESP6500_AA_AF"] = {"type": FUNCM, "field": "dbNSFP_ESP6500_AA_AF"}
    fConf["dbNSFP_ESP6500_EA_AF"] = {"type": FUNCM, "field": "dbNSFP_ESP6500_EA_AF"}
    fConf["dbNSFP_Ensembl_geneid"] = {"type": FUNCM, "field": "dbNSFP_Ensembl_geneid"}
    fConf["dbNSFP_Ensembl_transcriptid"] = {
        "type": FUNCM,
        "field": "dbNSFP_Ensembl_transcriptid",
    }
    fConf["dbNSFP_ExAC_AC"] = {"type": FUNCM, "field": "dbNSFP_ExAC_AC"}
    fConf["dbNSFP_ExAC_AF"] = {"type": FUNCM, "field": "dbNSFP_ExAC_AF"}
    fConf["dbNSFP_ExAC_AFR_AC"] = {"type": FUNCM, "field": "dbNSFP_ExAC_AFR_AC"}
    fConf["dbNSFP_ExAC_AFR_AF"] = {"type": FUNCM, "field": "dbNSFP_ExAC_AFR_AF"}
    fConf["dbNSFP_ExAC_AMR_AC"] = {"type": FUNCM, "field": "dbNSFP_ExAC_AMR_AC"}
    fConf["dbNSFP_ExAC_AMR_AF"] = {"type": FUNCM, "field": "dbNSFP_ExAC_AMR_AF"}
    fConf["dbNSFP_ExAC_Adj_AC"] = {"type": FUNCM, "field": "dbNSFP_ExAC_Adj_AC"}
    fConf["dbNSFP_ExAC_Adj_AF"] = {"type": FUNCM, "field": "dbNSFP_ExAC_Adj_AF"}
    fConf["dbNSFP_ExAC_EAS_AC"] = {"type": FUNCM, "field": "dbNSFP_ExAC_EAS_AC"}
    fConf["dbNSFP_ExAC_EAS_AF"] = {"type": FUNCM, "field": "dbNSFP_ExAC_EAS_AF"}
    fConf["dbNSFP_ExAC_FIN_AC"] = {"type": FUNCM, "field": "dbNSFP_ExAC_FIN_AC"}
    fConf["dbNSFP_ExAC_FIN_AF"] = {"type": FUNCM, "field": "dbNSFP_ExAC_FIN_AF"}
    fConf["dbNSFP_ExAC_NFE_AC"] = {"type": FUNCM, "field": "dbNSFP_ExAC_NFE_AC"}
    fConf["dbNSFP_ExAC_NFE_AF"] = {"type": FUNCM, "field": "dbNSFP_ExAC_NFE_AF"}
    fConf["dbNSFP_ExAC_SAS_AC"] = {"type": FUNCM, "field": "dbNSFP_ExAC_SAS_AC"}
    fConf["dbNSFP_ExAC_SAS_AF"] = {"type": FUNCM, "field": "dbNSFP_ExAC_SAS_AF"}
    fConf["dbNSFP_FATHMM_pred"] = {"type": FUNCM, "field": "dbNSFP_FATHMM_pred"}
    fConf["dbNSFP_GERP___RS"] = {"type": FUNCM, "field": "dbNSFP_GERP___RS"}
    fConf["dbNSFP_Interpro_domain"] = {"type": FUNCM, "field": "dbNSFP_Interpro_domain"}
    fConf["dbNSFP_MetaLR_pred"] = {"type": FUNCM, "field": "dbNSFP_MetaLR_pred"}
    fConf["dbNSFP_MetaSVM_pred"] = {"type": FUNCM, "field": "dbNSFP_MetaSVM_pred"}
    fConf["dbNSFP_MetaSVM_score"] = {"type": FUNCM, "field": "dbNSFP_MetaSVM_score"}
    fConf["dbNSFP_Polyphen2_HDIV_pred"] = {
        "type": FUNCM,
        "field": "dbNSFP_Polyphen2_HDIV_pred",
    }
    fConf["dbNSFP_Polyphen2_HVAR_pred"] = {
        "type": FUNCM,
        "field": "dbNSFP_Polyphen2_HVAR_pred",
    }
    fConf["dbNSFP_Reliability_index"] = {
        "type": FUNCM,
        "field": "dbNSFP_Reliability_index",
    }
    fConf["dbNSFP_SIFT_pred"] = {"type": FUNCM, "field": "dbNSFP_SIFT_pred"}
    fConf["dbNSFP_clinvar_trait"] = {"type": FUNCM, "field": "dbNSFP_clinvar_trait"}
    fConf["dbNSFP_clinvar_rs"] = {"type": FUNCM, "field": "dbNSFP_clinvar_rs"}
    fConf["dbNSFP_clinvar_clnsig"] = {"type": FUNCM, "field": "dbNSFP_clinvar_clnsig"}
    fConf["dbNSFP_aapos"] = {"type": FUNCM, "field": "dbNSFP_aapos"}
    fConf["dbSNP147.GMAF"] = {"type": FUNCM, "field": "dbSNP_GMAF"}
    fConf["dbSNP146.GMAF"] = {"type": FUNCM, "field": "dbSNP_GMAF"}
    fConf["spidex_dpsi_zscore"] = {"type": FUNCM, "field": "spidex_dpsi_zscore"}

    fConf["AC"] = {"type": TECHM, "field": "AC", "ALTRELATED": "true"}
    fConf["AF"] = {"type": TECHM, "field": "AF", "ALTRELATED": "true"}
    fConf["AN"] = {"type": TECHM, "field": "AN"}
    fConf["BaseQRankSum"] = {"type": TECHM, "field": "BaseQRankSum"}
    fConf["ClippingRankSum"] = {"type": TECHM, "field": "ClippingRankSum"}
    fConf["DP"] = {"type": TECHM, "field": "DP"}
    fConf["DS"] = {"type": TECHM, "field": "DS"}
    fConf["Dels"] = {"type": TECHM, "field": "Dels"}
    fConf["END"] = {"type": TECHM, "field": "END"}
    fConf["ExcessHet"] = {"type": TECHM, "field": "ExcessHet"}
    fConf["FS"] = {"type": TECHM, "field": "FS"}
    fConf["HaplotypeScore"] = {"type": TECHM, "field": "HaplotypeScore"}
    fConf["InbreedingCoeff"] = {"type": TECHM, "field": "InbreedingCoeff"}
    fConf["MLEAC"] = {"type": TECHM, "field": "MLEAC", "ALTRELATED": "true"}
    fConf["MLEAF"] = {"type": TECHM, "field": "MLEAF", "ALTRELATED": "true"}
    fConf["MQ"] = {"type": TECHM, "field": "MQ"}
    fConf["MQ0"] = {"type": TECHM, "field": "MQ0"}
    fConf["MQRankSum"] = {"type": TECHM, "field": "MQRankSum"}
    fConf["QD"] = {"type": TECHM, "field": "QD"}
    fConf["RAW_MQ"] = {"type": TECHM, "field": "RAW_MQ"}
    fConf["ReadPosRankSum"] = {"type": TECHM, "field": "ReadPosRankSum"}
    fConf["SOR"] = {"type": TECHM, "field": "SOR"}

    unknown_annotations_cache = {}

    # VERIFY Gene, Variant and VariantRelation models
    for key in fConf:
        field = fConf[key]
        if "type" not in field:
            log.warning("Annotation %s misconfiguration, missing type" % key)
            continue

        ftype = field["type"]
        if ftype == SKIPM:
            continue

        if "field" in field:
            prop_name = field["field"]
        else:
            prop_name = key

        if ftype == GENEM:
            if not hasattr(graph.Gene, prop_name):
                log.warning("Missing property %s in Gene model" % prop_name)
        elif ftype == FUNCM:
            if not hasattr(graph.Variant, prop_name):
                log.warning("Missing property %s in Variant model" % prop_name)
        elif ftype == TECHM:
            if not hasattr(graph.VariantRelation, prop_name):
                log.warning("Missing property %s in VariantRelation model" % prop_name)
        else:
            log.warning(f"Unknown type {ftype} for {key}")
            continue

    log.info("Updating probands...")
    # Determine probands in trios, to be excluded for frequency, issue #114
    graph.cypher("MATCH (d:Dataset) SET d.is_proband = false")
    cypher = \"""
MATCH
(d:Dataset)-[:IS_DESCRIBED_BY]->(proband:Phenotype),
(proband)-[:SON]->(father:Phenotype)<-[:IS_DESCRIBED_BY]-(:Dataset),
(proband)-[:SON]->(mother:Phenotype)<-[:IS_DESCRIBED_BY]-(:Dataset)
WHERE (father) <> (mother)
SET d.is_proband = true
\"""
    graph.cypher(cypher)

    log.info("Caching datasets...")
    probands = {}
    for d in graph.Dataset.nodes.all():
        probands[d.uuid] = d.is_proband

    log.info("Found %d probands", len(probands))

    import vcf

    vcf_reader = vcf.Reader(open(vcf_file))

    total_unfiltered = 0
    num_variants = 0
    datasets = None
    variants = {}
    genes = {}

    export_counter = 0

    for record in vcf_reader:

        total_unfiltered += 1
        _filter = record.FILTER

        # the FILTER column contains a semicolon-separated list
        # of failed filters. If all filters passed, the special
        # value PASS is used. This corresponds to an empty list
        # of failed filters.
        if len(_filter) > 0:
            # log.debug("Skipping variant with filter: %s", _filter)
            continue
        # else:
        #     log.info("Variant is good: %s", _filter)
        #     print(record.QUAL)

        num_variants += 1

        if num_variants % 1000 == 0:

            export(export_counter, variants)
            export_counter += 1
            variants = {}

            log.info("%d completed" % num_variants)
            self.update_state(state="PROGRESS", meta={"step": num_variants})

        # Count number of samples with the variant
        # Parsing a subsampled vcf a variant could be observed by
        # none of considered sample. i.e. all samples have GT = ./.
        # This case leads to a division by zero error in PyVCF.model.py:333
        num_samples_with_variant = 0
        for sample in record.samples:
            if sample.data.GT != "./.":
                num_samples_with_variant += 1

        if num_samples_with_variant == 0:
            log.warning("Skipping variant with %s samples", num_samples_with_variant)
            continue

        chromosome = record.CHROM
        start = record.POS
        end = record.end
        dbsnp_ids = record.ID
        if dbsnp_ids is not None:
            dbsnp_ids = dbsnp_ids.split(";")
        # genotype = record.genotype
        ref = record.REF
        alt = record.ALT
        quality = record.QUAL

        info = record.INFO
        heterozygosity = record.heterozygosity
        # alleles = record.alleles
        variant_type = record.var_type

        num_alt = len(alt)

        if self.type == RESOURCE_TYPE and datasets is None:
            datasets = {}
            for sample in record.samples:
                datasets[sample.sample] = sample.sample

        variant_properties = {}
        variant_properties["chromosome"] = chromosome
        variant_properties["start"] = start
        variant_properties["end"] = end
        variant_properties["ref"] = ref
        # variant_properties["alt"] = alt
        variant_properties["variant_type"] = variant_type
        variant_properties["dbSNP"] = dbsnp_ids

        # Temporary stored on the variant
        variant_properties["quality"] = quality
        variant_properties["filter"] = _filter

        rel_properties = {}
        rel_properties["quality"] = quality
        rel_properties["heterozygosity"] = heterozygosity
        rel_properties["num_alt"] = num_alt

        gene_properties = {}

        for alt_index, alt_value in enumerate(alt):
            variant_properties["alt"] = str(alt_value)
            rel_properties["allele_num"] = alt_index + 1

            for k in info:

                if k not in fConf:
                    if k not in unknown_annotations_cache:
                        unknown_annotations_cache[k] = True
                        log.warning("Unknown annotation type: %s" % k)
                    continue

                conf = fConf[k]

                if "type" not in conf:
                    log.warning("Annotation %s misconfiguration, missing type" % k)
                    continue
                if conf["type"] == SKIPM:
                    continue

                if "field" in conf:
                    field = conf["field"]
                else:
                    field = k

                value = info[k]
                ftype = type(value)

                if value is None:
                    continue

                if ftype is list:
                    length = len(value)

                    if length == 0:
                        continue

                    if "ALTRELATED" in conf:

                        if length != num_alt:
                            log.error(
                                "Wrong size for %s, expected %d found %d"
                                % (field, len(alt), length)
                            )

                        value = value[alt_index]

                    else:
                        pass
                        # Handle list of values
                        # print("%s = %s" % (field, value))

                # After list manipulation now value may be None
                if value is None:
                    continue

                if conf["type"] == GENEM:

                    if type(value) is list:
                        t = type(getattr(graph.Gene, field))
                        if t is not ArrayProperty:
                            if len(value) == 1:
                                value = value[0]
                            else:
                                log.warning(
                                    f"Gene: Found list instead of {t} in {field}"
                                )
                    if value is None:
                        continue
                    if type(value) is list and len(value) == 1 and value[0] is None:
                        continue

                    gene_properties[field] = value
                elif conf["type"] == TECHM:

                    if type(value) is list:
                        t = type(getattr(graph.VariantRelation, field))
                        if t is not ArrayProperty:
                            if len(value) == 1:
                                value = value[0]
                            # else:
                            #     log.warning("VariantRel: Found list instead of %s in %s" % (t, field))
                    if value is None:
                        continue
                    if type(value) is list and len(value) == 1 and value[0] is None:
                        continue

                    rel_properties[field] = value
                elif conf["type"] == FUNCM:

                    t = type(getattr(graph.Variant, field))
                    if type(value) is list:
                        if t is not ArrayProperty:
                            if len(value) == 1:
                                value = value[0]
                            # else:
                            #     log.warning("Variant: Found list instead of %s in %s" % (t, field))
                    elif t is ArrayProperty:
                        value = [value]

                    if value is None:
                        continue
                    if type(value) is list and len(value) == 1 and value[0] is None:
                        continue

                    variant_properties[field] = value

                else:
                    log.warning("Unknown type {} for {}", conf["type"], k)
                    continue

            if "alt" not in variant_properties:
                variant_properties["alt"] = "."
            elif variant_properties["alt"] is None:
                variant_properties["alt"] = "."

            for p in variant_properties:
                value = variant_properties[p]
                if value is None:
                    continue
                if type(value) is not list:
                    continue
                # Collect types of values in a set to remove duplicates
                types = {type(v) for v in value}
                # If set contains more than a type, convert all to string
                if len(types) > 1:
                    for k, v in enumerate(value):
                        variant_properties[p][k] = "%s" % v

            if (
                "MainEffect" in variant_properties
                and type(variant_properties["MainEffect"]) is list
            ):
                if len(variant_properties["MainEffect"]) == 1:
                    variant_properties["MainEffect"] = variant_properties["MainEffect"][
                        0
                    ]

            hasGene = True
            if len(gene_properties) <= 0:
                hasGene = False
            elif "geneName" not in gene_properties:
                hasGene = False
            elif (
                type(gene_properties["geneName"]) is list
                and len(gene_properties["geneName"]) == 1
            ):
                gene_properties["geneName"] = gene_properties["geneName"][0]
            if hasGene and gene_properties["geneName"] is None:
                hasGene = False

            if hasGene:
                geneName = gene_properties["geneName"]

                if geneName not in genes:

                    genes[geneName] = gene_properties

            observed = {}
            non_observed = {}
            for sample in record.samples:

                GT = sample.data.GT
                if GT == "./.":
                    continue

                sample_relationship = {}
                sample_relationship["GT"] = GT
                try:
                    sample_relationship["AD"] = sample.data.AD
                except BaseException:
                    pass
                try:
                    sample_relationship["DP"] = sample.data.DP
                except BaseException:
                    pass
                try:
                    sample_relationship["GQ"] = sample.data.GQ
                except BaseException:
                    pass
                try:
                    sample_relationship["PL"] = sample.data.PL
                except BaseException:
                    pass
                try:
                    sample_relationship["TP"] = sample.data.TP
                except BaseException:
                    pass
                try:
                    sample_relationship["PGT"] = sample.data.PGT
                except BaseException:
                    pass
                try:
                    sample_relationship["PID"] = sample.data.PID
                except BaseException:
                    pass

                prop = rel_properties.copy()
                prop.update(sample_relationship)

                dataset_uuid = None
                if self.type == FILE_TYPE:
                    d = NIGEndpoint.getSingleLinkedNode(self.fileNode.dataset)
                    dataset_uuid = d.uuid
                elif self.type == RESOURCE_TYPE:
                    if sample.sample in datasets:
                        dataset_uuid = datasets[sample.sample]

                if dataset_uuid is None:
                    continue

                if GT == "0|0" or GT == "0/0":
                    non_observed[dataset_uuid] = prop
                else:
                    observed[dataset_uuid] = prop

            num_obs = count_alleles(observed, probands)
            num_nonobs = count_alleles(non_observed, probands)

            if num_obs == 0 and num_nonobs == 0:
                variant_properties["total_allele"] = 0
                variant_properties["allele_count"] = 0
                variant_properties["allele_frequency"] = 0
            else:
                total_allele = num_obs + num_nonobs

                allele_count = 0
                num_hom = 0
                num_het = 0
                for d in observed:
                    data = observed.get(d)
                    GT = data.get("GT")
                    num_alleles = int(GT[0:1]) + int(GT[2:3])

                    if num_alleles == 1:
                        num_het += 1
                    elif num_alleles == 2:
                        num_hom += 2

                    allele_count += num_alleles

                variant_properties["total_allele"] = total_allele
                variant_properties["allele_count"] = allele_count
                variant_properties["num_hom"] = num_hom
                variant_properties["num_het"] = num_het
                freq = float(allele_count) / total_allele
                variant_properties["allele_frequency"] = freq

            # graph.Variant(**variant_properties).save()
            variants[num_variants] = variant_properties

            # log.warning("Saved variant %d" % variant.id)
    if len(variants) > 0:
        log.info("Exporting last %d variants..." % len(variants))
        export(export_counter, variants)
    else:
        log.info("No more variant to be exported")

    export_genes(genes)

    log.info("Total variants = %s", total_unfiltered)
    log.info("Total filtered variants = %s", num_variants)

    return num_variants
"""
