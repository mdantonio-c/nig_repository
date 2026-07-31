"""
Section 8 — VCF annotation with per-group allele frequencies.

Path A (§8.2, default): builds groups.txt from outliers_to_remove + pca_ita,
filtered to samples in the annotated cohort VCF, then runs bcftools +fill-tags
with general tags + pca_ita/outliers groups.

Path B (§8.3): if annotation.outliers_groups_file is supplied, runs the R
script to produce outliers_mixedgroups.txt with composite groups, then
annotates with the full group set.

Optional §8.4: produce no_out_commonVar_*.vcf.gz with outliers removed from
the merged VCF (enabled via annotation.remove_outliers_from_merge).
"""

_STEM = STEM   # from common.smk
_COHORT = COHORT  # from common.smk
_OGF  = config["annotation"]["outliers_groups_file"]


# ── Path B only: build mixed groups (§8.3) ────────────────────────────────────

rule filter_pca_groups_to_cohort:
    input:
        vcf=config["input"]["vcf"],
        tbi=config["input"]["vcf"] + ".tbi",
        outliers="results/outliers/outliers_to_remove_{cohort}.samples.txt",
        pca_ita="results/outliers/pca_ita_{cohort}.txt",
    output:
        outliers="results/annotate/outliers_to_remove_{cohort}.cohort_samples.txt",
        pca_ita="results/annotate/pca_ita_{cohort}.cohort_samples.txt",
    log:
        "logs/annotate/filter_pca_groups_{cohort}.log",
    conda:
        "../envs/bcftools.yaml"
    shell:
        """
        cohort_samples=$(mktemp)
        trap 'rm -f "$cohort_samples"' EXIT

        bcftools query -l {input.vcf} > "$cohort_samples"
        awk 'NR==FNR {{keep[$1]=1; next}} ($1 in keep)' "$cohort_samples" {input.outliers} > {output.outliers}
        awk 'NR==FNR {{keep[$1]=1; next}} ($1 in keep)' "$cohort_samples" {input.pca_ita} > {output.pca_ita}

        printf 'Cohort samples: ' > {log}
        wc -l < "$cohort_samples" >> {log}
        printf 'Cohort outliers: ' >> {log}
        wc -l < {output.outliers} >> {log}
        printf 'Cohort pca_ita: ' >> {log}
        wc -l < {output.pca_ita} >> {log}
        """

if _OGF:

    rule build_mixed_groups:
        input:
            outliers_groups=_OGF,
            outliers_to_remove="results/annotate/outliers_to_remove_{cohort}.cohort_samples.txt",
            pca_ita="results/annotate/pca_ita_{cohort}.cohort_samples.txt",
        output:
            mixed="results/annotate/outliers_mixedgroups_{cohort}.txt",
        log:
            "logs/annotate/build_mixed_groups_{cohort}.log",
        conda:
            "../envs/r.yaml"
        script:
            "../scripts/generate_mixed_groups.R"


# ── Path A: build simple groups.txt (§8.2) ────────────────────────────────────

rule build_groups:
    input:
        vcf=config["input"]["vcf"],
        tbi=config["input"]["vcf"] + ".tbi",
        outliers="results/annotate/outliers_to_remove_{cohort}.cohort_samples.txt",
        pca_ita="results/annotate/pca_ita_{cohort}.cohort_samples.txt",
    output:
        groups="results/annotate/groups_{cohort}.txt",
    log:
        "logs/annotate/build_groups_{cohort}.log",
    conda:
        "../envs/bcftools.yaml"
    shell:
        """
        awk '{{print $1"\toutliers"}}' {input.outliers} >  {output.groups}
        awk '{{print $1"\tpca_ita"}}'  {input.pca_ita}  >> {output.groups}
        """


# ── Annotate (both paths converge here) ──────────────────────────────────────

rule annotate_vcf:
    input:
        vcf=config["input"]["vcf"],
        tbi=config["input"]["vcf"] + ".tbi",
        groups=get_groups_file,
    output:
        vcf="results/annotated/groups_INFOtags_{cohort}.vcf.gz",
        tbi="results/annotated/groups_INFOtags_{cohort}.vcf.gz.tbi",
    params:
        fill_tags=config["annotation"]["fill_tags"],
    log:
        "logs/annotate/annotate_vcf_{cohort}.log",
    benchmark:
        "benchmarks/annotate/annotate_vcf_{cohort}.tsv"
    threads: config["threads"]["bcftools"]
    conda:
        "../envs/bcftools.yaml"
    shell:
        """
        bcftools +fill-tags {input.vcf} \
            -Oz -o {output.vcf} \
            -- \
            -t {params.fill_tags} \
            -S {input.groups} \
            2>{log}
        bcftools index -t {output.vcf} 2>>{log}
        """


# ── §8.4 optional: remove outliers from merged VCF ───────────────────────────

if config["annotation"]["remove_outliers_from_merge"]:

    rule drop_outliers_from_merge:
        input:
            vcf=f"results/merge/{_STEM}.vcf.gz",
            tbi=f"results/merge/{_STEM}.vcf.gz.tbi",
            outliers=f"results/outliers/outliers_to_remove_{_COHORT}.samples.txt",
            cohort_vcf=config["input"]["vcf"],
            ref_vcf=config["reference"]["cohort_vcf"],
        output:
            vcf=f"results/merge/no_out_{_STEM}.vcf.gz",
            tbi=f"results/merge/no_out_{_STEM}.vcf.gz.tbi",
        log:
            f"logs/annotate/drop_outliers_merge_{_COHORT}.log",
        benchmark:
            f"benchmarks/annotate/drop_outliers_merge_{_COHORT}.tsv"
        params:
            sample_scope=config["annotation"].get("outlier_removal_scope", "all"),
        threads: config["threads"]["bcftools"]
        conda:
            "../envs/bcftools.yaml"
        shell:
            """
            selected_outliers=$(mktemp)
            trap 'rm -f "$selected_outliers"' EXIT

            case "{params.sample_scope}" in
                all)
                    cp {input.outliers} "$selected_outliers"
                    ;;
                cohort_only)
                    bcftools query -l {input.cohort_vcf} \
                        | awk 'NR==FNR {{keep[$1]=1; next}} ($1 in keep)' - {input.outliers} \
                        > "$selected_outliers"
                    ;;
                reference_only)
                    bcftools query -l {input.ref_vcf} \
                        | awk 'NR==FNR {{keep[$1]=1; next}} ($1 in keep)' - {input.outliers} \
                        > "$selected_outliers"
                    ;;
                *)
                    echo "Invalid annotation.outlier_removal_scope: {params.sample_scope}" > {log}
                    exit 1
                    ;;
            esac

            bcftools view \
                --force-samples \
                -S ^"$selected_outliers" \
                --threads {threads} \
                -Oz -o {output.vcf} \
                {input.vcf} 2>{log}
            bcftools index -t {output.vcf} 2>>{log}
            """
