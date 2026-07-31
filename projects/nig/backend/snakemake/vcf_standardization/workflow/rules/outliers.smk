"""
Section 6.2 — Outlier detection via Mahalanobis distance.

Produces:
  - outliers_to_remove.txt   (FID + ID, no header)
  - outliers_to_remove.samples.txt   (outlier sample IDs, single column)
  - pca_ita.txt              (non-outlier sample IDs)
  - pca_plot_{cohort}.png    (PC1 vs PC2 coloured by outlier status)
  - macroarea_plot_{cohort}.png  (if covariates.macroarea_xlsx provided)
"""

_STEM = STEM   # from common.smk


rule detect_outliers:
    input:
        eigenvec=f"results/pca/pca_{_STEM}.eigenvec",
        macroarea=lambda wc: (
            config["covariates"]["macroarea_xlsx"]
            if config["covariates"]["macroarea_xlsx"]
            else []
        ),
    output:
        outliers="results/outliers/outliers_to_remove_{cohort}.txt",
        outlier_samples="results/outliers/outliers_to_remove_{cohort}.samples.txt",
        pca_ita="results/outliers/pca_ita_{cohort}.txt",
        pca_plot=f"results/outliers/pca_plot_{{cohort}}.png",
        macroarea_plot=(
            f"results/outliers/macroarea_plot_{{cohort}}.png"
            if config["covariates"]["macroarea_xlsx"]
            else []
        ),
    params:
        n_components=config["pca"]["n_components"],
        mahal_quantile=config["pca"]["mahalanobis_quantile"],
        macroarea_xlsx=config["covariates"]["macroarea_xlsx"],
    log:
        "logs/outliers/detect_outliers_{cohort}.log",
    benchmark:
        "benchmarks/outliers/detect_outliers_{cohort}.tsv"
    conda:
        "../envs/r.yaml"
    script:
        "../scripts/detect_outliers.R"
