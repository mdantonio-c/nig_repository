"""
Shared helpers: target resolution, conditional input selection.
Imported by Snakefile before all other rule modules.
"""

COHORT = config["cohort_name"]
REF    = config["reference"]["cohort_name"]
STEM   = f"commonVar_{REF}_{COHORT}"


def get_cohort_vcf_for_merge():
    """Return the normalized (and optionally de-related) cohort VCF."""
    if config["relatedness"]["enabled"]:
        return f"results/relatedness/unrelated_{COHORT}.vcf.gz"
    return f"results/normalized/newID_{COHORT}.vcf.gz"


def get_groups_file(wildcards=None):
    """Select groups file path based on whether outliers_groups_file is supplied."""
    og = config["annotation"]["outliers_groups_file"]
    if og:
        return f"results/annotate/outliers_mixedgroups_{COHORT}.txt"
    return f"results/annotate/groups_{COHORT}.txt"


def get_pca_sex_file(wildcards=None):
    """Return the expanded PCA sex file when sex metadata is configured."""
    if config["relatedness"].get("sex_metadata_csv", ""):
        return f"results/pca/{STEM}.sex.txt"
    return []


def get_pca_sex_flag(wildcards=None):
    """Return PLINK2 --update-sex flag for PCA import when available."""
    if config["relatedness"].get("sex_metadata_csv", ""):
        return f"--update-sex results/pca/{STEM}.sex.txt"
    return ""


def get_final_targets(cfg):
    targets = [
        f"results/annotated/groups_INFOtags_{COHORT}.vcf.gz",
        f"results/annotated/groups_INFOtags_{COHORT}.vcf.gz.tbi",
        f"results/outliers/pca_plot_{COHORT}.png",
    ]
    if cfg["covariates"]["macroarea_xlsx"]:
        targets.append(f"results/outliers/macroarea_plot_{COHORT}.png")
    if cfg["annotation"]["remove_outliers_from_merge"]:
        targets.append(f"results/merge/no_out_{STEM}.vcf.gz")
    if cfg["trio"]["enabled"]:
        for subset in ("parents", "probands"):
            targets.append(f"results/annotated/groups_INFOtags_{COHORT}_{subset}.vcf.gz")
    return targets
