"""
Section 5 — Merge the normalized cohort with the ITvarGM reference cohort.

Two routes selectable via config.merge.tool:
  "bcftools" → §5.1: isec → extract common → bcftools merge
  "plink"    → §5.2: vcf→bed → common vars → bmerge → recode back to VCF

Output (both routes): results/merge/commonVar_{ref}_{cohort}.vcf.gz + .tbi
"""

_STEM = STEM   # imported from common.smk: commonVar_{REF}_{COHORT}
_COHORT = COHORT  # imported from common.smk
_REF = REF  # imported from common.smk


# ─── bcftools route (§5.1) ───────────────────────────────────────────────────

if config["merge"]["tool"] == "bcftools":

    # Index the reference cohort (rule is skipped if .tbi already exists)
    rule index_reference:
        input:
            vcf=config["reference"]["cohort_vcf"],
        output:
            tbi=config["reference"]["cohort_vcf"] + ".tbi",
        log:
            "logs/merge/index_reference.log",
        conda:
            "../envs/bcftools.yaml"
        shell:
            "bcftools index -t {input.vcf} 2>{log}"

    rule common_ids:
        input:
            ref_vcf=config["reference"]["cohort_vcf"],
            ref_tbi=config["reference"]["cohort_vcf"] + ".tbi",
            cohort_vcf=get_cohort_vcf_for_merge(),
            cohort_tbi=get_cohort_vcf_for_merge() + ".tbi",
        output:
            ids=f"results/merge/common_ids_{_COHORT}.txt",
        log:
            f"logs/merge/common_ids_{_COHORT}.log",
        benchmark:
            f"benchmarks/merge/common_ids_{_COHORT}.tsv"
        threads: config["threads"]["bcftools"]
        conda:
            "../envs/bcftools.yaml"
        shell:
            """
            bcftools isec -n=2 -w1 \
                {input.ref_vcf} \
                {input.cohort_vcf} \
                -Oz \
            | bcftools query -f '%ID\n' \
            > {output.ids} 2>{log}
            """

    rule extract_common_ref:
        input:
            vcf=config["reference"]["cohort_vcf"],
            tbi=config["reference"]["cohort_vcf"] + ".tbi",
            ids=f"results/merge/common_ids_{_COHORT}.txt",
        output:
            vcf=temp(f"results/merge/common_var_{_REF}_for_{_COHORT}.vcf.gz"),
            tbi=temp(f"results/merge/common_var_{_REF}_for_{_COHORT}.vcf.gz.tbi"),
        log:
            f"logs/merge/extract_common_ref_{_REF}_{_COHORT}.log",
        benchmark:
            f"benchmarks/merge/extract_common_ref_{_REF}_{_COHORT}.tsv"
        threads: config["threads"]["bcftools"]
        conda:
            "../envs/bcftools.yaml"
        shell:
            """
            bcftools view \
                --include 'ID=@{input.ids}' \
                --threads {threads} \
                -Oz -o {output.vcf} \
                {input.vcf} 2>{log}
            bcftools index -t {output.vcf} 2>>{log}
            """

    rule extract_common_cohort:
        input:
            vcf=get_cohort_vcf_for_merge(),
            tbi=get_cohort_vcf_for_merge() + ".tbi",
            ids=f"results/merge/common_ids_{_COHORT}.txt",
        output:
            vcf=temp(f"results/merge/common_var_{_COHORT}.vcf.gz"),
            tbi=temp(f"results/merge/common_var_{_COHORT}.vcf.gz.tbi"),
        log:
            f"logs/merge/extract_common_cohort_{_COHORT}.log",
        benchmark:
            f"benchmarks/merge/extract_common_cohort_{_COHORT}.tsv"
        threads: config["threads"]["bcftools"]
        conda:
            "../envs/bcftools.yaml"
        shell:
            """
            bcftools view \
                --include 'ID=@{input.ids}' \
                --threads {threads} \
                -Oz -o {output.vcf} \
                {input.vcf} 2>{log}
            bcftools index -t {output.vcf} 2>>{log}
            """

    rule merge_cohorts:
        input:
            ref_vcf=f"results/merge/common_var_{_REF}_for_{_COHORT}.vcf.gz",
            ref_tbi=f"results/merge/common_var_{_REF}_for_{_COHORT}.vcf.gz.tbi",
            cohort_vcf=f"results/merge/common_var_{_COHORT}.vcf.gz",
            cohort_tbi=f"results/merge/common_var_{_COHORT}.vcf.gz.tbi",
        output:
            vcf=f"results/merge/{_STEM}.vcf.gz",
            tbi=f"results/merge/{_STEM}.vcf.gz.tbi",
        log:
            f"logs/merge/merge_cohorts_{_STEM}.log",
        benchmark:
            f"benchmarks/merge/merge_cohorts_{_STEM}.tsv"
        threads: config["threads"]["bcftools"]
        conda:
            "../envs/bcftools.yaml"
        shell:
            """
            bcftools merge \
                --force-samples \
                --threads {threads} \
                -Oz -o {output.vcf} \
                {input.ref_vcf} {input.cohort_vcf} 2>{log}
            bcftools index -t {output.vcf} 2>>{log}
            """


# ─── plink route (§5.2) ──────────────────────────────────────────────────────

elif config["merge"]["tool"] == "plink":

    rule vcf_to_bed_ref:
        input:
            vcf=config["reference"]["cohort_vcf"],
            tbi=config["reference"]["cohort_vcf"] + ".tbi",
        output:
            bed=temp(f"results/merge/plink/{REF}.bed"),
            bim=temp(f"results/merge/plink/{REF}.bim"),
            fam=temp(f"results/merge/plink/{REF}.fam"),
        params:
            prefix=f"results/merge/plink/{REF}",
        log:
            f"logs/merge/vcf_to_bed_{REF}.log",
        benchmark:
            f"benchmarks/merge/vcf_to_bed_{REF}.tsv"
        threads: config["threads"]["plink"]
        conda:
            "../envs/plink.yaml"
        shell:
            """
            plink \
                --vcf {input.vcf} \
                --double-id \
                --make-bed \
                --threads {threads} \
                --out {params.prefix} \
                2>{log}
            """

    rule vcf_to_bed_cohort:
        input:
            vcf=get_cohort_vcf_for_merge(),
            tbi=get_cohort_vcf_for_merge() + ".tbi",
        output:
            bed=temp("results/merge/plink/{cohort}.bed"),
            bim=temp("results/merge/plink/{cohort}.bim"),
            fam=temp("results/merge/plink/{cohort}.fam"),
        params:
            prefix="results/merge/plink/{cohort}",
        log:
            "logs/merge/vcf_to_bed_{cohort}.log",
        benchmark:
            "benchmarks/merge/vcf_to_bed_{cohort}.tsv"
        threads: config["threads"]["plink"]
        conda:
            "../envs/plink.yaml"
        shell:
            """
            plink \
                --vcf {input.vcf} \
                --double-id \
                --allow-extra-chr \
                --make-bed \
                --threads {threads} \
                --out {params.prefix} \
                2>{log}
            """

    rule common_vars_plink:
        input:
            ref_bim=f"results/merge/plink/{REF}.bim",
            cohort_bim="results/merge/plink/{cohort}.bim",
        output:
            common="results/merge/plink/common_{cohort}.vars",
        log:
            "logs/merge/common_vars_{cohort}.log",
        run:
            with open(input.ref_bim) as f:
                ref_vars = {line.split()[1] for line in f}
            with open(input.cohort_bim) as f:
                cohort_vars = {line.split()[1] for line in f}
            common = sorted(ref_vars & cohort_vars)
            with open(output.common, "w") as f:
                f.write("\n".join(common) + "\n")
            with open(log[0], "w") as f:
                f.write(f"{len(common)} common variants\n")

    rule extract_common_plink_ref:
        input:
            bed=f"results/merge/plink/{REF}.bed",
            bim=f"results/merge/plink/{REF}.bim",
            fam=f"results/merge/plink/{REF}.fam",
            common="results/merge/plink/common_{cohort}.vars",
        output:
            bed=temp(f"results/merge/plink/{REF}_common_{{cohort}}.bed"),
            bim=temp(f"results/merge/plink/{REF}_common_{{cohort}}.bim"),
            fam=temp(f"results/merge/plink/{REF}_common_{{cohort}}.fam"),
        params:
            in_prefix=f"results/merge/plink/{REF}",
            out_prefix=f"results/merge/plink/{REF}_common_{{cohort}}",
        log:
            f"logs/merge/extract_common_plink_{REF}_{{cohort}}.log",
        benchmark:
            f"benchmarks/merge/extract_common_plink_{REF}_{{cohort}}.tsv"
        threads: config["threads"]["plink"]
        conda:
            "../envs/plink.yaml"
        shell:
            """
            plink \
                --bfile {params.in_prefix} \
                --extract {input.common} \
                --make-bed \
                --threads {threads} \
                --out {params.out_prefix} \
                2>{log}
            """

    rule extract_common_plink_cohort:
        input:
            bed="results/merge/plink/{cohort}.bed",
            bim="results/merge/plink/{cohort}.bim",
            fam="results/merge/plink/{cohort}.fam",
            common="results/merge/plink/common_{cohort}.vars",
        output:
            bed=temp("results/merge/plink/{cohort}_common.bed"),
            bim=temp("results/merge/plink/{cohort}_common.bim"),
            fam=temp("results/merge/plink/{cohort}_common.fam"),
        params:
            in_prefix="results/merge/plink/{cohort}",
            out_prefix="results/merge/plink/{cohort}_common",
        log:
            "logs/merge/extract_common_plink_{cohort}.log",
        benchmark:
            "benchmarks/merge/extract_common_plink_{cohort}.tsv"
        threads: config["threads"]["plink"]
        conda:
            "../envs/plink.yaml"
        shell:
            """
            plink \
                --bfile {params.in_prefix} \
                --extract {input.common} \
                --allow-extra-chr \
                --make-bed \
                --threads {threads} \
                --out {params.out_prefix} \
                2>{log}
            """

    rule bmerge:
        input:
            ref_bed=f"results/merge/plink/{REF}_common_{{cohort}}.bed",
            ref_bim=f"results/merge/plink/{REF}_common_{{cohort}}.bim",
            ref_fam=f"results/merge/plink/{REF}_common_{{cohort}}.fam",
            cohort_bed="results/merge/plink/{cohort}_common.bed",
            cohort_bim="results/merge/plink/{cohort}_common.bim",
            cohort_fam="results/merge/plink/{cohort}_common.fam",
        output:
            bed=temp(f"results/merge/plink/{_STEM}.bed"),
            bim=temp(f"results/merge/plink/{_STEM}.bim"),
            fam=temp(f"results/merge/plink/{_STEM}.fam"),
        params:
            ref_prefix=f"results/merge/plink/{REF}_common_{{cohort}}",
            cohort_prefix="results/merge/plink/{cohort}_common",
            out_prefix=f"results/merge/plink/{_STEM}",
        log:
            f"logs/merge/bmerge_{_STEM}.log",
        benchmark:
            f"benchmarks/merge/bmerge_{_STEM}.tsv"
        threads: config["threads"]["plink"]
        conda:
            "../envs/plink.yaml"
        shell:
            """
            plink \
                --bfile {params.ref_prefix} \
                --bmerge {params.cohort_prefix} \
                --make-bed \
                --threads {threads} \
                --out {params.out_prefix} \
                2>{log}
            """

    rule plink_to_vcf:
        input:
            bed=f"results/merge/plink/{_STEM}.bed",
            bim=f"results/merge/plink/{_STEM}.bim",
            fam=f"results/merge/plink/{_STEM}.fam",
        output:
            vcf=f"results/merge/{_STEM}.vcf.gz",
            tbi=f"results/merge/{_STEM}.vcf.gz.tbi",
        params:
            in_prefix=f"results/merge/plink/{_STEM}",
            out_prefix=f"results/merge/plink/{_STEM}_vcf",
        log:
            f"logs/merge/plink_to_vcf_{_STEM}.log",
        benchmark:
            f"benchmarks/merge/plink_to_vcf_{_STEM}.tsv"
        threads: config["threads"]["plink"]
        conda:
            "../envs/plink.yaml"
        shell:
            """
            plink \
                --bfile {params.in_prefix} \
                --recode vcf-iid bgz \
                --threads {threads} \
                --out {params.out_prefix} \
                2>{log}
            mv {params.out_prefix}.vcf.gz {output.vcf}
            bcftools index -t {output.vcf} 2>>{log}
            """
