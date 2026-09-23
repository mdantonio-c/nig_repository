"""
Section 4 — Remove related individuals (PLINK 2.0 KING).
Only included in DAG when config.relatedness.enabled is true.
When relatedness.sex_metadata_csv is set, a PLINK2-compatible sex file is
generated from the CSV and passed via --update-sex so that sex chromosomes
are handled correctly; otherwise the analysis falls back to --autosome.
"""

# ── helpers ────────────────────────────────────────────────────────────────────
_sex_csv = config["relatedness"].get("sex_metadata_csv", "")


def _king_sex_input(wildcards):
    """Return sex_file path when available, else empty list (no dependency)."""
    return f"{RESULT_ROOT}/relatedness/sex_file.txt" if _sex_csv else []


_sex_flag = (
    f"--update-sex {RESULT_ROOT}/relatedness/sex_file.txt"
    if _sex_csv
    else "--autosome"
)
# ──────────────────────────────────────────────────────────────────────────────

if config["relatedness"]["enabled"]:

    if _sex_csv:

        rule prepare_sex_file:
            """Convert sample_metadata CSV to PLINK2 --update-sex format.
            Output columns: #FID  IID  SEX  (1=male, 2=female, 0=unknown).
            FID is set to 0 because --vcf input assigns FID=0 by default.
            """
            input:
                csv=_sex_csv,
            output:
                sex_file=f"{RESULT_ROOT}/relatedness/sex_file.txt",
            log:
                f"{LOG_ROOT}/relatedness/prepare_sex_file.log",
            run:
                import pandas as pd

                df = pd.read_csv(input.csv)
                df.columns = df.columns.str.strip()
                sex_map = {"male": 1, "female": 2}
                out = pd.DataFrame(
                    {
                        "#FID": 0,
                        "IID": df["sample"].str.strip(),
                        "SEX": (
                            df["sex"]
                            .str.strip()
                            .str.lower()
                            .str.strip('"')  # Remove quotes if present
                            .map(sex_map)
                            .fillna(0)
                            .astype(int)
                        ),
                    }
                )
                out.to_csv(output.sex_file, sep="\t", index=False)
                with open(log[0], "w") as fh:
                    fh.write(f"Written {len(out)} samples to {output.sex_file}\n")

    rule king_table:
        input:
            vcf=f"{RESULT_ROOT}/normalized/newID_{{cohort}}.vcf.gz",
            tbi=f"{RESULT_ROOT}/normalized/newID_{{cohort}}.vcf.gz.tbi",
            sex_file=_king_sex_input,
        output:
            cutoff_ids=f"{RESULT_ROOT}/relatedness/{{cohort}}.king.cutoff.out.id",
            king_table=f"{RESULT_ROOT}/relatedness/{{cohort}}.kin0",
        params:
            prefix=f"{RESULT_ROOT}/relatedness/{{cohort}}",
            king_cutoff=config["relatedness"]["king_cutoff"],
            king_table_filter=config["relatedness"]["king_table_filter"],
            sex_flag=_sex_flag,
        log:
            f"{LOG_ROOT}/relatedness/king_table_{{cohort}}.log",
        benchmark:
            f"{BENCHMARK_ROOT}/relatedness/king_table_{{cohort}}.tsv"
        threads: config["threads"]["plink"]
        conda:
            "../envs/plink.yaml"
        shell:
            """
            plink2 \\
                --vcf {input.vcf} \\
                --split-par hg38 \\
                {params.sex_flag} \\
                --make-king-table \\
                --king-table-filter {params.king_table_filter} \\
                --king-cutoff {params.king_cutoff} \\
                --threads {threads} \\
                --out {params.prefix} \\
                2>{log}
            """

    rule related_list:
        input:
            cutoff_ids=f"{RESULT_ROOT}/relatedness/{{cohort}}.king.cutoff.out.id",
        output:
            related=f"{RESULT_ROOT}/relatedness/related_samples_{{cohort}}.txt",
        log:
            f"{LOG_ROOT}/relatedness/related_list_{{cohort}}.log",
        run:
            import pandas as pd
            df = pd.read_csv(input.cutoff_ids, sep="\t", header=None, names=["IID"])
            df = df[df["IID"] != "#IID"]
            #df = pd.read_csv(input.cutoff_ids, sep="\t" header=0) #, comment="#",
            if df.empty:
                open(output.related, "w").close()
                with open(log[0], "w") as fh:
                    fh.write("No related samples found; empty exclusion list written.\n")
            else:
                # col = df.columns[0]
                # df[[col]].to_csv(output.related, index=False, header=False)
                df[["IID"]].to_csv(output.related, index=False, header=False)
                with open(log[0], "w") as fh:
                    fh.write(f"Related samples to remove: {len(df)}\n")

    rule drop_related:
        input:
            vcf=f"{RESULT_ROOT}/normalized/newID_{{cohort}}.vcf.gz",
            tbi=f"{RESULT_ROOT}/normalized/newID_{{cohort}}.vcf.gz.tbi",
            related=f"{RESULT_ROOT}/relatedness/related_samples_{{cohort}}.txt",
        output:
            vcf=f"{RESULT_ROOT}/relatedness/unrelated_{{cohort}}.vcf.gz",
            tbi=f"{RESULT_ROOT}/relatedness/unrelated_{{cohort}}.vcf.gz.tbi",
        log:
            f"{LOG_ROOT}/relatedness/drop_related_{{cohort}}.log",
        benchmark:
            f"{BENCHMARK_ROOT}/relatedness/drop_related_{{cohort}}.tsv"
        threads: config["threads"]["bcftools"]
        conda:
            "../envs/bcftools.yaml"
        shell:
            """
            bcftools view \\
                --force-samples \\
                -S ^{input.related} \\
                --threads {threads} \\
                -Oz -o {output.vcf} \\
                {input.vcf} 2>{log}
            bcftools index -t {output.vcf} 2>>{log}
            """
