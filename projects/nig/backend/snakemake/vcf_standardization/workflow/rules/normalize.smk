"""
Section 3.1 — VCF normalization.

Steps:
  1. (conditional) rename chromosomes to chr-prefixed style using no_chr_rename table
  2. bcftools annotate --rename-chrs + bcftools norm -f hg38.fa + bcftools annotate -x ID -I +'%CHROM:%POS:%REF:%ALT'

Output: results/normalized/newID_{cohort}.vcf.gz + .tbi
"""


# ── Step 1 (only when input does NOT already have chr prefix) ────────────────

if not config["input"]["has_chr_prefix"]:

    rule add_chr_prefix:
        input:
            vcf=config["input"]["vcf"],
            tbi=config["input"]["vcf"] + ".tbi",
            rename=config["conventions"]["no_chr_rename"],
        output:
            vcf=temp("results/normalized/chrpfx_{cohort}.vcf.gz"),
            tbi=temp("results/normalized/chrpfx_{cohort}.vcf.gz.tbi"),
        log:
            "logs/normalize/add_chr_prefix_{cohort}.log",
        benchmark:
            "benchmarks/normalize/add_chr_prefix_{cohort}.tsv"
        threads: config["threads"]["bcftools"]
        conda:
            "../envs/bcftools.yaml"
        shell:
            """
            bcftools annotate \
                --rename-chrs {input.rename} \
                --threads {threads} \
                -Oz -o {output.vcf} \
                {input.vcf} 2>{log}
            bcftools index -t {output.vcf} 2>>{log}
            """

    _pre_norm_vcf = rules.add_chr_prefix.output.vcf

else:
    _pre_norm_vcf = config["input"]["vcf"]


# ── Step 2: normalize + re-ID ────────────────────────────────────────────────

rule normalize_and_reid:
    input:
        vcf=_pre_norm_vcf,
        fasta=config["reference"]["fasta"],
        fai=config["reference"]["fasta"] + ".fai",
        chr_rename=config["conventions"]["chr_rename"],
    output:
        vcf="results/normalized/newID_{cohort}.vcf.gz",
        tbi="results/normalized/newID_{cohort}.vcf.gz.tbi",
    log:
        "logs/normalize/normalize_and_reid_{cohort}.log",
    benchmark:
        "benchmarks/normalize/normalize_and_reid_{cohort}.tsv"
    threads: config["threads"]["bcftools"]
    conda:
        "../envs/bcftools.yaml"
    shell:
        """
        bcftools annotate \
            --rename-chrs {input.chr_rename} \
            --threads {threads} \
            -Ou {input.vcf} \
        | bcftools norm \
            -Ou -f {input.fasta} \
        | bcftools annotate \
            -Oz -x ID -I +'%CHROM:%POS:%REF:%ALT' \
            -o {output.vcf} \
            2>{log}
        bcftools index -t {output.vcf} 2>>{log}
        """
