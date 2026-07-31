# Section 8.3 — Generate composite groups from outliers_groups.txt.
#
# Reads a user-supplied two-column TSV (ID, comma-separated groups) and
# the pipeline-derived pca_ita / outliers classification, merges them,
# then expands composite groups (ita_cardio, ita_neuro_male, etc.)
# following the rules from the protocol.
#
# Outputs: outliers_mixedgroups.txt  (ID <tab> expanded comma-separated groups)

log_con <- file(snakemake@log[[1]], open = "wt")
sink(log_con, type = "output")
sink(log_con, type = "message")

# ── 1. Read pipeline-derived classification ───────────────────────────────────
outliers <- read.table(snakemake@input[["outliers_to_remove"]],
                       sep = "\t", header = FALSE, stringsAsFactors = FALSE)
colnames(outliers)[1] <- "ID"
outliers$pca_class <- "outliers"

pca_ita <- read.table(snakemake@input[["pca_ita"]],
                      sep = "\t", header = FALSE, stringsAsFactors = FALSE)
colnames(pca_ita)[1] <- "ID"
pca_ita$pca_class <- "pca_ita"

pca_df <- rbind(outliers[, c("ID", "pca_class")],
                pca_ita[, c("ID", "pca_class")])

# ── 2. Read user-supplied outliers_groups file ────────────────────────────────
og <- read.table(snakemake@input[["outliers_groups"]],
                 sep = "\t", header = FALSE, stringsAsFactors = FALSE)
colnames(og) <- c("ID", "groups")

# ── 3. Merge, injecting/overriding the pca_class ─────────────────────────────
merged <- merge(og, pca_df, by = "ID", all.x = TRUE)
merged$pca_class[is.na(merged$pca_class)] <- "outliers"

# Replace any existing pca_ita/outliers tag with the pipeline-derived one
strip_pca <- function(grp_str) {
  tags <- unlist(strsplit(gsub(" ", "", grp_str), ","))
  tags <- tags[!tags %in% c("pca_ita", "outliers")]
  tags
}
merged$groups_clean <- mapply(
  function(g, cls) paste(c(strip_pca(g), cls), collapse = ","),
  merged$groups, merged$pca_class
)

# ── 4. Expand composite groups (protocol §8.3) ───────────────────────────────
generate_groups <- function(group_str) {
  groups <- unlist(strsplit(gsub(" ", "", group_str), ","))
  new_groups <- character(0)
  has <- function(x) x %in% groups

  if (has("pca_ita") && has("male"))   new_groups <- c(new_groups, "ita_male")
  if (has("pca_ita") && has("female")) new_groups <- c(new_groups, "ita_female")

  for (pheno in c("cardio", "neuro", "cancer", "not_affected")) {
    if (has("pca_ita") && has(pheno)) {
      new_groups <- c(new_groups, paste0("ita_", pheno))
      if (has("male"))   new_groups <- c(new_groups, paste0("ita_", pheno, "_male"))
      if (has("female")) new_groups <- c(new_groups, paste0("ita_", pheno, "_female"))
    }
  }

  paste(unique(c(groups, new_groups)), collapse = ",")
}

merged$groups_expanded <- sapply(merged$groups_clean, generate_groups)

# ── 5. Write output ───────────────────────────────────────────────────────────
write.table(merged[, c("ID", "groups_expanded")],
            file = snakemake@output[["mixed"]],
            sep = "\t", quote = FALSE, row.names = FALSE, col.names = FALSE)

cat(sprintf("Wrote %d entries to %s\n", nrow(merged), snakemake@output[["mixed"]]))

sink(type = "message")
sink(type = "output")
close(log_con)
