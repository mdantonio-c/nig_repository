from typing import Dict, List

from nig.endpoints import NIGEndpoint
from restapi import decorators
from restapi.connectors import neo4j

# from restapi.utilities.logs import log


class Search(NIGEndpoint):

    labels = ["search"]

    # Compute a dynamic list of elements is suitable only for one
    # or very few properties. For a greater number of properties
    # the loading time of the search form is really too slow

    # def get_list_element(self, label, field, optional=True):

    #     cypher = "MATCH (n: %s) return distinct n.%s as f ORDER by f"\
    #         % (label, field)

    #     result = graph.cypher(cypher)
    #     data = []
    #     if optional:
    #         data.append({"id": "", "value": ""})
    #     for row in result:

    #         value = row[0]
    #         # if type(value) is list and len(value) == 1:
    #         #     value = value[0]

    #         data.append({"id": value, "value": value})

    #     return data

    def get_chr_list(self):

        return [
            {"id": "", "value": ""},
            {"id": "chr1", "value": "chr1"},
            {"id": "chr2", "value": "chr2"},
            {"id": "chr3", "value": "chr3"},
            {"id": "chr4", "value": "chr4"},
            {"id": "chr5", "value": "chr5"},
            {"id": "chr6", "value": "chr6"},
            {"id": "chr7", "value": "chr7"},
            {"id": "chr8", "value": "chr8"},
            {"id": "chr9", "value": "chr9"},
            {"id": "chr10", "value": "chr10"},
            {"id": "chr11", "value": "chr11"},
            {"id": "chr12", "value": "chr12"},
            {"id": "chr13", "value": "chr13"},
            {"id": "chr14", "value": "chr14"},
            {"id": "chr15", "value": "chr15"},
            {"id": "chr16", "value": "chr16"},
            {"id": "chr17", "value": "chr17"},
            {"id": "chr18", "value": "chr18"},
            {"id": "chr19", "value": "chr19"},
            {"id": "chr20", "value": "chr20"},
            {"id": "chr21", "value": "chr21"},
            {"id": "chr22", "value": "chr22"},
            {"id": "chrX", "value": "chrX"},
            {"id": "chrY", "value": "chrY"},
            {"id": "chrM", "value": "chrM"},
        ]

    """
    @decorators.auth.require()
    @decorators.endpoint(
        path="/search",
        summary="Retrieve the search schema",
        responses={
            200: "Search schema successfully retrieved",
        },
    )
    def get(self):

        schema = []
        variants_sections = []
        phenotype_sections = []
        geo_sections = []
        tech_sections = []

        # variant_type_list = self.get_list_element("Variant", "variant_type")
        variant_type_list = [
            {"id": "", "value": ""},
            {"id": "snp", "value": "SNPs"},
            {"id": "indel", "value": "INDELs"},
        ]
        macroarea_list = [
            {"id": "", "value": ""},
            {"id": "north italy", "value": "Northern regions"},
            {"id": "center italy", "value": "Central regions"},
            {"id": "south italy", "value": "Southern regions"},
            {"id": "sardinia", "value": "Sardinia"},
        ]

        platform_list = [
            {"id": "", "value": ""},
            {"id": "SNP-array", "value": "SNP-array"},
        ]
        chr_list = self.get_chr_list()
        # main_effects = self.get_list_element("Variant", "MainEffect")

        # ################## ROW ################## #

        variants_sections.append(
            {
                "key": "geneName",
                "type": "text",
                "size": "12",
                "label": "Gene",
            }
        )

        # ################## ROW ################## #

        variants_sections.append(
            {
                "key": "variant_type",
                "type": "select",
                "size": "4",
                "label": "Variant type",
                "options": variant_type_list,
            }
        )
        variants_sections.append(
            {
                "key": "ref",
                "type": "text",
                "size": "4",
                "label": "Reference",
            }
        )

        variants_sections.append(
            {
                "key": "alt",
                "type": "text",
                "size": "4",
                "label": "Alternate",
            }
        )

        # ################## ROW ################## #

        variants_sections.append(
            {
                "key": "chromosome",
                "type": "select",
                "size": "4",
                "label": "Chromosome",
                "options": chr_list,
            }
        )

        variants_sections.append(
            {
                "key": "start",
                "type": "int",
                "size": "4",
                "label": "Start position",
            }
        )

        variants_sections.append(
            {
                "key": "end",
                "type": "int",
                "size": "4",
                "label": "End position",
            }
        )

        # ################## ROW ################## #

        variants_sections.append(
            {
                "key": "main_effect",
                "type": "autocomplete",
                "size": "4",
                "label": "Main effect",
                "select_label": "label",
                "select_id": "id",
            }
        )

        # ################## ROW ################## #

        # phenotype_sections.append(
        #     {
        #         "key": "study_uuid",
        #         "type": "text",
        #         "size": "6",
        #         "label": "Study uuid",
        #     }
        # )

        # phenotype_sections.append(
        #     {
        #         "key": "dataset_uuid",
        #         "type": "text",
        #         "size": "6",
        #         "label": "Dataset uuid",
        #     }
        # )

        # ################## ROW ################## #

        # phenotype_sections.append(
        #     {
        #         "key": "phenotype_uuid",
        #         "type": "text",
        #         "size": "6",
        #         "label": "Phenotype uuid",
        #     }
        # )
        # phenotype_sections.append(
        #     {
        #         "key": "name",
        #         "type": "text",
        #         "size": "6",
        #         "label": "Identification code",
        #     }
        # )

        # ################## ROW ################## #

        phenotype_sections.append(
            {
                "key": "sex",
                "type": "select",
                "size": "4",
                "label": "Sex",
                "options": [
                    {"id": "", "value": ""},
                    {"id": "male", "value": "male"},
                    {"id": "female", "value": "female"},
                ],
            }
        )
        # phenotype_sections.append(
        #     {
        #         "key": "HPO",
        #         "type": "autocomplete",
        #         "multiple": "true",
        #         # "required": "false",
        #         "label": "HPO terms",
        #         # "description": "",
        #         # "islink": "true",
        #         # "model_key": "_hpo",
        #         # "select_label": "label",
        #         # "select_id": "hpo_id"
        #     }
        # )

        # phenotype_sections.append(
        #     {
        #         "key": "birthday",
        #         "type": "date",
        #         "label": "Date of birth",
        #     }
        # )
        # phenotype_sections.append(
        #     {
        #         "key": "deathday",
        #         "type": "date",
        #         "label": "Date of death",
        #     }
        # )
        # phenotype_sections.append(
        #     {
        #         "key": "birthplace",
        #         "type": "autocomplete",
        #         "required": "false",
        #         "label": "City of birth",
        #         "description": "",
        #         "islink": "true",
        #         "model_key": "_birth_place",
        #         "select_label": "city",
        #         "select_id": "id"
        #     }
        # )
        phenotype_sections.append(
            {
                "key": "HPO",
                "type": "autocomplete",
                "multiple": "false",
                "size": "8",
                "label": "HPO terms",
                "model_key": "_hpo",
                "select_label": "label",
                "select_id": "hpo_id",
            }
        )

        # ################## ROW ################## #
        geo_sections.append(
            {
                "key": "macroarea",
                "type": "select",
                "size": "4",
                "label": "Italian macro geographical area",
                "options": macroarea_list,
            }
        )
        # ################## ROW ################## #

        tech_sections.append(
            {
                "key": "platform",
                "type": "select",
                "size": "4",
                "label": "Sequencing platform",
                "options": platform_list,
            }
        )

        # ################## MERGE ALL ################## #

        schema.append({"key": "variants", "sections": variants_sections})

        schema.append({"key": "phenotype", "sections": phenotype_sections})

        schema.append({"key": "geographical", "sections": geo_sections})

        schema.append({"key": "technical", "sections": tech_sections})

        return self.response(schema)
    """

    def cleanFilters(self, filters):
        clean_filters = {}
        for k in filters:
            v = filters[k]
            if v is None:
                continue
            if v == "":
                continue
            clean_filters[k] = v
        return clean_filters

    def queryNode(self, node, filters, schema=None):

        import neomodel

        if len(filters) == 0:
            return "(%s)" % node

        apply_filters = []
        for k in filters:
            v = filters[k]
            if schema is not None:
                attr = None
                if hasattr(schema, k):
                    attr = getattr(schema, k)

            if attr is None:
                apply_filters.append(f"{k}: '{v}'")
            elif isinstance(attr, neomodel.properties.IntegerProperty):
                apply_filters.append(f"{k}: {v}")
            elif isinstance(attr, neomodel.properties.FloatProperty):
                apply_filters.append(f"{k}: {v}")
            else:
                apply_filters.append(f"{k}: '{v}'")

        return "({} {{{}}})".format(node, ", ".join(apply_filters))

    def getAutocomplete(self, data, label="label"):
        if data is None:
            return data
        if data == "":
            return data
        if label not in data:
            return data
        return data[label]

    @decorators.auth.require()
    @decorators.endpoint(
        path="/search",
        summary="Search variants",
        responses={
            200: "Variants successfully retrieved",
        },
    )
    def post(self):

        graph = neo4j.get_instance()
        filters = self.get_input()

        HARD_LIMIT = 200
        SOFT_LIMIT = 250

        # study_filters = {}
        # dataset_filters = {}
        variant_filters = {}
        gene_filters = {}
        geo_filters = {}
        hpo_filters = {}
        phenotype_filters = {}
        technical_filters = {}

        # study_filters["uuid"] = filters.get("study_uuid", "")
        # dataset_filters["uuid"] = filters.get("dataset_uuid", "")
        variant_filters["variant_type"] = filters.get("variant_type", "")
        variant_filters["chromosome"] = filters.get("chromosome", "")
        variant_filters["start"] = filters.get("start", "")
        variant_filters["end"] = filters.get("end", "")
        variant_filters["ref"] = filters.get("ref", "")
        variant_filters["alt"] = filters.get("alt", "")

        variant_filters["MainEffect"] = self.getAutocomplete(
            filters.get("main_effect", "")
        )

        gene_filters["geneName"] = filters.get("geneName", "").upper()
        geo_filters["macroarea"] = filters.get("macroarea", "")
        hpo_filters["hpo_id"] = filters.get("HPO", "")
        phenotype_filters["uuid"] = filters.get("phenotype_uuid", "")
        phenotype_filters["name"] = filters.get("name", "")
        phenotype_filters["sex"] = filters.get("sex", "")

        technical_filters["platform"] = filters.get("platform", "")

        # study_filters = self.cleanFilters(study_filters)
        # dataset_filters = self.cleanFilters(dataset_filters)
        variant_filters = self.cleanFilters(variant_filters)
        gene_filters = self.cleanFilters(gene_filters)
        geo_filters = self.cleanFilters(geo_filters)
        hpo_filters = self.cleanFilters(hpo_filters)
        phenotype_filters = self.cleanFilters(phenotype_filters)
        technical_filters = self.cleanFilters(technical_filters)

        # hpo_id: {label: '...', hpo_id: '...'}
        if "hpo_id" in hpo_filters and "hpo_id" in hpo_filters["hpo_id"]:
            hpo_filters["hpo_id"] = hpo_filters["hpo_id"]["hpo_id"]

        variant_start = None
        variant_end = None
        if "start" in variant_filters and "end" in variant_filters:
            variant_start = int(variant_filters["start"])
            variant_end = int(variant_filters["end"])
            del variant_filters["start"]
            del variant_filters["end"]

        data = []

        returned_nodes = []
        returned_nodes.append("variant")

        cypher = "MATCH (file:File)"
        cypher += " WHERE ((file)<-[:OBSERVED_IN]-(:Variant))"
        cypher += " RETURN count(distinct file) as total"
        result = graph.cypher(cypher)
        total_samples = 0
        for row in result:
            total_samples = row[0]
            break

        cypher = ""

        matchGene = len(gene_filters) > 0

        # ##### MATCH (variant) #######

        cypher += "MATCH "
        cypher += self.queryNode("variant:Variant", variant_filters, graph.Variant)

        if matchGene:
            cypher += "-[:LOCATED_IN]->"
            cypher += self.queryNode("gene:Gene", gene_filters, graph.Gene)
            returned_nodes.append("gene")

        if variant_start is not None and variant_end is not None:
            # verify gap length.. max 100k?
            cypher += " WHERE variant.start >= %d AND variant.end <= %d" % (
                variant_start,
                variant_end,
            )

        if matchGene:
            cypher += " WITH variant, gene"
        else:
            cypher += " WITH variant"
        cypher += " LIMIT %d" % SOFT_LIMIT

        # ##### MATCH (variant)--(file) #######
        cypher += " MATCH "
        cypher += "(variant)"
        cypher += "-[observed_variant:OBSERVED_IN]->"
        cypher += "(file:File)"
        # #############################

        # ##### MATCH (variant)----(technical) #######
        if len(technical_filters) > 0:
            cypher += " MATCH "
            cypher += "(file)"
            cypher += "<-[:CONTAINS]-"
            cypher += "(dataset:Dataset)"
            cypher += "-[:IS_DESCRIBED_BY]->"
            cypher += self.queryNode(
                "technical:TechnicalMetadata",
                technical_filters,
                graph.TechnicalMetadata,
            )

        # ##### MATCH (variant)----(phenotype) #######
        if (
            len(phenotype_filters) == 0
            and len(geo_filters) == 0
            and len(hpo_filters) == 0
        ):
            cypher += " OPTIONAL MATCH "
        else:
            cypher += " MATCH "
        cypher += "(file)"
        cypher += "<-[:CONTAINS]-"
        cypher += "(dataset:Dataset)"
        cypher += "-[:IS_DESCRIBED_BY]->"
        cypher += self.queryNode(
            "phenotype:Phenotype", phenotype_filters, graph.Phenotype
        )

        # ##### MATCH (variant)--(gene) #######
        if not matchGene:
            cypher += " OPTIONAL MATCH "
            cypher += "(variant)"
            cypher += "-[:LOCATED_IN]->"
            cypher += self.queryNode("gene:Gene", gene_filters, graph.Gene)
            returned_nodes.append("gene")
        # #############################

        cypher += " WITH variant, gene, file, phenotype "

        # ##### MATCH (phenotype)--(HPO) #######
        searched_hpos = None
        if "hpo_id" in hpo_filters:
            cypher += (
                " WHERE ((phenotype)-[:DESCRIBED_BY]->(:HPO)-[:GENERALIZED_BY]->(:HPO)<-[:GENERALIZED_BY]-(:HPO {hpo_id: '%s'}))"
                % hpo_filters["hpo_id"]
            )
            try:
                searched_hpo = graph.HPO.nodes.get(hpo_id=hpo_filters["hpo_id"])
                # Converting HPO to higher level parent
                searched_hpos = []
                for h in searched_hpo.generalized_parent.all():
                    if h.hide_node:
                        continue
                    searched_hpos.append(h.hpo_id)
            except graph.HPO.DoesNotExist:
                pass

        # ##### MATCH (phenotype)--(GeoData) #######
        if len(geo_filters) == 0:
            cypher += " OPTIONAL MATCH "
        else:
            cypher += " MATCH "
        cypher += "(phenotype)"
        cypher += "-[:BIRTH_PLACE]->"
        cypher += self.queryNode("geo:GeoData", geo_filters, graph.GeoData)

        cypher += " RETURN "
        cypher += ", ".join(returned_nodes)
        cypher += ", count(distinct file) as observed_in"
        cypher += ", collect(distinct phenotype) as phenotype_distribution"
        cypher += ", collect(geo.macroarea) as geo_distribution"

        returned_nodes.append("observed_in")
        returned_nodes.append("phenotype_distribution")
        returned_nodes.append("geo_distribution")

        cypher += " ORDER BY id(variant) ASC"
        cypher += " LIMIT %d" % HARD_LIMIT

        # log.critical(cypher)

        query_result = graph.cypher(cypher)
        counter = 0
        phenocache: Dict[str, List[str]] = {}
        hpo_cache = {}

        AFFECTED_LABEL = "yes"
        NOT_AFFECTED_LABEL = "no"
        for row in query_result:

            counter += 1

            result = {"counter": counter}

            variant = None
            if "variant" in returned_nodes:
                node = row[returned_nodes.index("variant")]
                if node is not None:
                    variant = graph.Variant.inflate(node)
                    result["variant"] = self.getJsonResponse(variant)

            if "gene" in returned_nodes:
                node = row[returned_nodes.index("gene")]
                if node is not None:
                    gene = graph.Gene.inflate(node)
                    result["gene"] = self.getJsonResponse(gene)

            if "phenotype" in returned_nodes:
                node = row[returned_nodes.index("phenotype")]
                if node is not None:
                    phenotype = graph.Phenotype.inflate(node)
                    result["phenotype"] = self.getJsonResponse(
                        phenotype, view_public_only=True
                    )

            num_observed = 0
            if "observed_in" in returned_nodes:
                num_observed = row[returned_nodes.index("observed_in")]
                result["observed_in"] = num_observed
                result["total_samples"] = total_samples
                if total_samples > 0:
                    result["observed_perc"] = num_observed / total_samples
                else:
                    result["observed_perc"] = 0

            if "phenotype_distribution" in returned_nodes:
                phenotypes = row[returned_nodes.index("phenotype_distribution")]
                sex_distribution = []
                affected_distribution = []
                hpo_distribution = []
                confirmed = 0
                for node in phenotypes:
                    p = graph.Phenotype.inflate(node)
                    sex_distribution.append(p.sex)

                    if p.uuid not in phenocache:
                        phenocache[p.uuid] = []
                        for hpo in p.hpo.all():
                            if hpo.hide_node:
                                # log.critical("Skipping %s" % hpo.hpo_id)
                                continue
                            # Apply filters:
                            # if "hpo_id" in hpo_filters:
                            #     if hpo.hpo_id != hpo_filters["hpo_id"]:
                            #         continue
                            # # Converting HPO to higher level parent
                            for h in hpo.generalized_parent.all():
                                if h.hide_node:
                                    # log.critical("Skipping %s" % h.hpo_id)
                                    continue
                                # hpo = h
                                if (
                                    searched_hpos is not None
                                    and h.hpo_id not in searched_hpos
                                ):
                                    continue

                                if h.hpo_id not in phenocache[p.uuid]:
                                    phenocache[p.uuid].append(h.hpo_id)
                                    hpo_cache[h.hpo_id] = h

                            # OLD: no HPO generalization
                            # if hpo.hpo_id not in phenocache[p.uuid]:
                            #     phenocache[p.uuid].append(hpo.hpo_id)
                            #     hpo_cache[hpo.hpo_id] = hpo

                    hpo_distribution += phenocache[p.uuid]
                    if len(phenocache[p.uuid]) > 0:
                        affected_distribution.append(AFFECTED_LABEL)
                    else:
                        affected_distribution.append(NOT_AFFECTED_LABEL)

                    if variant is not None and p.confirmed_variant.is_connected(
                        variant
                    ):
                        confirmed += 1

                keys = set(sex_distribution)
                distribution = {}
                tot = 0
                for k in keys:
                    n = sex_distribution.count(k)
                    tot += n
                    p = n / num_observed
                    distribution[k] = p
                distribution["unknown"] = (num_observed - tot) / num_observed
                result["sex_distribution"] = distribution

                keys = set(affected_distribution)
                distribution = {}
                for k in keys:
                    p = affected_distribution.count(k) / num_observed
                    distribution[k] = p
                result["affected_distribution"] = distribution

                keys = set(hpo_distribution)
                naffected = affected_distribution.count(AFFECTED_LABEL)

                distribution = {}
                for k in keys:
                    if naffected == 0:
                        p = 0
                    else:
                        p = hpo_distribution.count(k) / naffected
                    hpo = hpo_cache[k]
                    distribution[k] = {
                        "percentage": p,
                        "hpo_id": hpo.hpo_id,
                        "label": hpo.label,
                        "description": hpo.description,
                    }
                result["hpo_distribution"] = distribution
                result["confirmed"] = confirmed

            if "geo_distribution" in returned_nodes:
                node = row[returned_nodes.index("geo_distribution")]
                keys = set(node)
                distribution = {}
                for k in keys:
                    p = node.count(k) / num_observed
                    distribution[k] = p

                result["geo_distribution"] = distribution

            data.append(result)

        return self.response(data)
