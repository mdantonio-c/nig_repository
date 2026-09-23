"""
Shared helpers: target resolution, conditional input selection.
Imported by Snakefile before all other rule modules.
"""

COHORT = config["cohort_name"]
REF    = config["reference"]["cohort_name"]
STEM   = f"commonVar_{REF}_{COHORT}"
RESULT_ROOT = config.get("output_dir", "results").rstrip("/")
LOG_ROOT = config.get("log_dir", "logs").rstrip("/")
BENCHMARK_ROOT = config.get("benchmark_dir", "benchmarks").rstrip("/")


def get_cohort_vcf_for_merge():
    """Return the normalized (and optionally de-related) cohort VCF."""
    if config["relatedness"]["enabled"]:
        return f"{RESULT_ROOT}/relatedness/unrelated_{COHORT}.vcf.gz"
    return f"{RESULT_ROOT}/normalized/newID_{COHORT}.vcf.gz"


def get_groups_file(wildcards=None):
    """Select groups file path based on whether outliers_groups_file is supplied."""
    og = config["annotation"]["outliers_groups_file"]
    if og:
        return f"{RESULT_ROOT}/annotate/outliers_mixedgroups_{COHORT}.txt"
    return f"{RESULT_ROOT}/annotate/groups_{COHORT}.txt"


def get_pca_sex_file(wildcards=None):
    """Return the expanded PCA sex file when sex metadata is configured."""
    if config["relatedness"].get("sex_metadata_csv", ""):
        return f"{RESULT_ROOT}/pca/{STEM}.sex.txt"
    return []


def get_pca_sex_flag(wildcards=None):
    """Return PLINK2 --update-sex flag for PCA import when available."""
    if config["relatedness"].get("sex_metadata_csv", ""):
        return f"--update-sex {RESULT_ROOT}/pca/{STEM}.sex.txt"
    return ""


def get_final_targets(cfg):
    targets = [
        f"{RESULT_ROOT}/annotated/groups_INFOtags_{COHORT}.vcf.gz",
        f"{RESULT_ROOT}/annotated/groups_INFOtags_{COHORT}.vcf.gz.tbi",
        f"{RESULT_ROOT}/outliers/pca_plot_{COHORT}.png",
    ]
    if cfg["covariates"]["macroarea_file"]:
        targets.append(f"{RESULT_ROOT}/outliers/macroarea_plot_{COHORT}.png")
    if cfg["annotation"]["remove_outliers_from_merge"]:
        targets.extend([
            f"{RESULT_ROOT}/merge/no_out_{STEM}.vcf.gz",
            f"{RESULT_ROOT}/merge/no_out_{STEM}.vcf.gz.tbi",
        ])
    if cfg["trio"]["enabled"]:
        for subset in ("parents", "probands"):
            targets.extend([
                f"{RESULT_ROOT}/trio/{COHORT}_{subset}.vcf.gz",
                f"{RESULT_ROOT}/trio/{COHORT}_{subset}.vcf.gz.tbi",
            ])
    return targets
