"""
Section 7 — Split trio VCF into parents and probands subsets.
Only included in DAG when config.trio.enabled is true.
"""

if config["trio"]["enabled"]:

    for _subset, _samples_key in [("parents", "parents_file"), ("probands", "probands_file")]:

        rule:
            name: f"split_trio_{_subset}"
            input:
                vcf=config["input"]["vcf"],
                tbi=config["input"]["vcf"] + ".tbi",
                samples=config["trio"][_samples_key],
            output:
                vcf=f"results/trio/{{cohort}}_{_subset}.vcf.gz",
                tbi=f"results/trio/{{cohort}}_{_subset}.vcf.gz.tbi",
            log:
                f"logs/trio/split_trio_{_subset}_{{cohort}}.log",
            benchmark:
                f"benchmarks/trio/split_trio_{_subset}_{{cohort}}.tsv"
            threads: config["threads"]["bcftools"]
            conda:
                "../envs/bcftools.yaml"
            shell:
                """
                bcftools view \
                    --force-samples \
                    -S {input.samples} \
                    --threads {threads} \
                    -Oz -o {output.vcf} \
                    {input.vcf} 2>{log}
                bcftools index -t {output.vcf} 2>>{log}
                """
