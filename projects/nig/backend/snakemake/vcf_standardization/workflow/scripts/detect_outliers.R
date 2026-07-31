library(MASS)
library(ggplot2)
library(dplyr)

# ── inputs / params from Snakemake ────────────────────────────────────────────
eigenvec_path  <- snakemake@input[["eigenvec"]]
n_pcs          <- as.integer(snakemake@params[["n_components"]])
mahal_quantile <- as.numeric(snakemake@params[["mahal_quantile"]])
macroarea_xlsx <- snakemake@params[["macroarea_xlsx"]]

out_outliers   <- snakemake@output[["outliers"]]
out_outlier_samples <- snakemake@output[["outlier_samples"]]
out_pca_ita    <- snakemake@output[["pca_ita"]]
out_pca_plot   <- snakemake@output[["pca_plot"]]

log_con <- file(snakemake@log[[1]], open = "wt")
sink(log_con, type = "output")
sink(log_con, type = "message")

# ── 1. Load eigenvectors ──────────────────────────────────────────────────────
ev <- read.table(eigenvec_path, header = TRUE, comment.char = "", check.names = FALSE)
# Handle PLINK2 format: clean up column names and create FID/ID columns
if ("#IID" %in% colnames(ev)) {
  colnames(ev)[colnames(ev) == "#IID"] <- "ID"
  ev$FID <- ev$ID  # Create FID column same as ID for PLINK2 format
} else if (!"ID" %in% colnames(ev)) {
  ev$ID <- ev[[1]]  # Use first column as ID
  ev$FID <- ev$ID   # Create FID column same as ID
}

# ── 2. Mahalanobis outlier detection ─────────────────────────────────────────
pcs       <- as.matrix(ev[, paste0("PC", seq_len(n_pcs))])
center    <- colMeans(pcs)
covmat    <- cov(pcs)
mahal     <- mahalanobis(pcs, center, covmat)
threshold <- qchisq(mahal_quantile, df = n_pcs)
ev$is_outlier <- mahal > threshold

cat(sprintf("Mahalanobis threshold (chi2 %.4f, df=%d): %.4f\n",
            mahal_quantile, n_pcs, threshold))
cat(sprintf("Outliers detected: %d / %d\n", sum(ev$is_outlier), nrow(ev)))

# ── 3. Write outliers_to_remove.txt (FID + ID, no header) ────────────────────
# Handle case where FID and ID are the same (PLINK2 format)
if (all(ev$FID == ev$ID)) {
  outliers_df <- ev[ev$is_outlier, c("ID", "ID")]
} else {
  outliers_df <- ev[ev$is_outlier, c("FID", "ID")]
}
write.table(outliers_df, file = out_outliers,
            sep = "\t", row.names = FALSE, col.names = FALSE, quote = FALSE)

outlier_ids <- ev[ev$is_outlier, "ID", drop = FALSE]
write.table(outlier_ids, file = out_outlier_samples,
            sep = "\t", row.names = FALSE, col.names = FALSE, quote = FALSE)

# ── 4. Write pca_ita.txt (non-outlier IDs, single column) ────────────────────
pca_ita_ids <- ev[!ev$is_outlier, "ID", drop = FALSE]
write.table(pca_ita_ids, file = out_pca_ita,
            sep = "\t", row.names = FALSE, col.names = FALSE, quote = FALSE)

# ── 5. PCA plot: PC1 vs PC2 coloured by outlier status ───────────────────────
p_outlier <- ggplot(ev, aes(x = PC1, y = PC2, color = is_outlier)) +
  geom_point(alpha = 0.7, size = 1.2) +
  scale_color_manual(values = c("FALSE" = "black", "TRUE" = "red"),
                     name = "Outlier") +
  theme_minimal() +
  coord_fixed() +
  labs(
    title = "PCA — Mahalanobis outlier detection",
    subtitle = sprintf("%d outliers detected (quantile %.4f, %d PCs)",
                       sum(ev$is_outlier), mahal_quantile, n_pcs),
    x = "PC1", y = "PC2"
  )

ggsave(out_pca_plot, p_outlier, width = 7, height = 6, dpi = 150)

# ── 6. Macroarea plot (optional) ──────────────────────────────────────────────
if (nchar(macroarea_xlsx) > 0 && length(snakemake@output[["macroarea_plot"]]) > 0) {
  library(readxl)
  labels <- read_excel(macroarea_xlsx)

  # Accept any column named ID (case-insensitive) and MACROAREA
  colnames(labels) <- toupper(colnames(labels))
  if (!"ID" %in% colnames(labels) || !"MACROAREA" %in% colnames(labels)) {
    warning("macroarea_xlsx must have columns 'ID' and 'MACROAREA'. Skipping macroarea plot.")
  } else {
    ev_merged <- merge(ev, labels[, c("ID", "MACROAREA")], by = "ID", all.x = TRUE)
    custom_colors <- c(
      NORD = "#1f78b4", CENTRO = "#ff7f00",
      SUD  = "#d16ba5", SARDEGNA = "purple4"
    )
    p_macro <- ggplot(ev_merged, aes(PC1, PC2, color = MACROAREA)) +
      geom_point(size = 1, alpha = 0.7) +
      scale_colour_manual(values = custom_colors, na.value = "grey70") +
      coord_equal() +
      theme_light() +
      labs(
        title = "PCA by Macroarea",
        x = "PC1", y = "PC2", color = "Macroarea"
      )
    out_macro <- snakemake@output[["macroarea_plot"]]
    ggsave(out_macro, p_macro, width = 7, height = 6, dpi = 150)
  }
}

sink(type = "message")
sink(type = "output")
close(log_con)
