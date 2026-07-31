"""
Section 6 — PCA with PLINK 2.

Uses allele-weights approach (plink2 --pca allele-wts) which produces
eigenvec and eigenval files used downstream by the outlier detection script.
"""

_STEM = STEM   # from common.smk


if config["relatedness"].get("sex_metadata_csv", ""):

    rule prepare_pca_sex_file:
        """Expand cohort sex metadata to all samples in the merged PCA VCF.
        Output columns: #FID  IID  SEX. Unknown/reference samples are SEX=0.
        """
        input:
            vcf=f"results/merge/{_STEM}.vcf.gz",
            tbi=f"results/merge/{_STEM}.vcf.gz.tbi",
            csv=config["relatedness"]["sex_metadata_csv"],
        output:
            sex_file=f"results/pca/{_STEM}.sex.txt",
        log:
            f"logs/pca/prepare_sex_file_{_STEM}.log",
        conda:
            "../envs/bcftools.yaml"
        run:
            import csv
            import subprocess

            sample_ids = subprocess.check_output(
                ["bcftools", "query", "-l", input.vcf],
                text=True,
            ).splitlines()

            sex_map = {"male": 1, "female": 2}
            sex_by_sample = {}
            with open(input.csv, newline="") as fh:
                reader = csv.DictReader(fh)
                fields = {name.strip().lower(): name for name in (reader.fieldnames or [])}
                sample_col = fields.get("sample")
                sex_col = fields.get("sex")
                if not sample_col or not sex_col:
                    raise ValueError("sex_metadata_csv must contain 'sample' and 'sex' columns")
                for row in reader:
                    sample_id = row[sample_col].strip()
                    sex = row[sex_col].strip().lower().strip('"')
                    sex_by_sample[sample_id] = sex_map.get(sex, 0)

            known = 0
            with open(output.sex_file, "w") as fh:
                fh.write("#FID\tIID\tSEX\n")
                for sample_id in sample_ids:
                    sex = sex_by_sample.get(sample_id, 0)
                    known += int(sex != 0)
                    fh.write(f"0\t{sample_id}\t{sex}\n")
            unknown = len(sample_ids) - known
            with open(log[0], "w") as fh:
                fh.write(f"Written {len(sample_ids)} samples to {output.sex_file}\n")
                fh.write(f"Known sex: {known}; unknown/reference: {unknown}\n")


rule make_pgen:
    input:
        vcf=f"results/merge/{_STEM}.vcf.gz",
        tbi=f"results/merge/{_STEM}.vcf.gz.tbi",
        sex_file=get_pca_sex_file,
    output:
        pgen=temp(f"results/pca/{_STEM}.pgen"),
        pvar=temp(f"results/pca/{_STEM}.pvar"),
        psam=temp(f"results/pca/{_STEM}.psam"),
    params:
        prefix=f"results/pca/{_STEM}",
        sex_flag=get_pca_sex_flag,
    log:
        f"logs/pca/make_pgen_{_STEM}.log",
    benchmark:
        f"benchmarks/pca/make_pgen_{_STEM}.tsv"
    threads: config["threads"]["plink"]
    conda:
        "../envs/plink.yaml"
    shell:
        """
        plink2 \
            --vcf {input.vcf} \
            {params.sex_flag} \
            --make-pgen \
            --threads {threads} \
            --out {params.prefix} \
            2>{log}
        """


rule plink_pca:
    input:
        pgen=f"results/pca/{_STEM}.pgen",
        pvar=f"results/pca/{_STEM}.pvar",
        psam=f"results/pca/{_STEM}.psam",
    output:
        eigenvec=f"results/pca/pca_{_STEM}.eigenvec",
        eigenval=f"results/pca/pca_{_STEM}.eigenval",
        acount=f"results/pca/pca_{_STEM}.acount",
    params:
        in_prefix=f"results/pca/{_STEM}",
        out_prefix=f"results/pca/pca_{_STEM}",
        n_components=config["pca"]["n_components"],
    log:
        f"logs/pca/plink_pca_{_STEM}.log",
    benchmark:
        f"benchmarks/pca/plink_pca_{_STEM}.tsv"
    threads: config["threads"]["plink"]
    conda:
        "../envs/plink.yaml"
    shell:
        """
        plink2 \
            --pfile {params.in_prefix} \
            --freq counts \
            --pca {params.n_components} allele-wts vcols=chrom,ref,alt \
            --threads {threads} \
            --out {params.out_prefix} \
            2>{log}
        """
