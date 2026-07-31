# NIG VCF Standardization Pipeline

This is a standalone workflow bundled with NIG. It is not invoked by the
existing platform job launcher, which uses Snakemake 6.4; run it with the
dedicated environment supplied in this directory (Snakemake 9.19.0).

`data/ITvarGM.vcf.gz` and its index are deployed only on the NIG VM and are
intentionally ignored by Git. Do not stage, commit, or distribute them. Before
running, provide your cohort VCF and its index under `data/` (or update
`config/config.yaml`) and provide `resources/hg38.fa` with its `.fai` index.

Snakemake pipeline implementing the VCF standardization protocol described in
*Standardizzazione file VCF per piattaforma NIG* (Devito et al., UniTo).

## Workflow overview

1. **Normalize** — add `chr` prefix if missing, left-align indels against hg38, rewrite IDs as `CHROM:POS:REF:ALT` (§3.1)
2. **Relatedness filter** *(opt-in)* — PLINK 2 KING kinship, remove related samples (§4)
3. **Trio split** *(opt-in)* — split into parents / probands VCFs before annotation (§7)
4. **Merge with ITvarGM** — intersect common variants, merge cohorts; bcftools (§5.1) or PLINK (§5.2) route (§5)
5. **PCA** — PLINK 2, allele-weights approach (§6)
6. **Outlier detection** — Mahalanobis distance on PC1–PC10, threshold at chi² 0.999 quantile (§6.2)
7. **Annotate** — `bcftools +fill-tags` with general statistics + per-group allele frequencies (§8)
8. **Drop outliers from merge** *(opt-in)* — produce outlier-free merged VCF for re-PCA (§8.4)

## Requirements

- [Conda / Mamba](https://docs.conda.io/)
- Snakemake ≥ 8

## Setup

### 1. Create the Snakemake runner environment

```bash
conda env create -f vcf_stand_env.yaml
conda activate standard_vcf
```

### 2. Create per-tool conda environments

```bash
conda env create -f workflow/envs/bcftools.yaml
conda env create -f workflow/envs/plink.yaml
conda env create -f workflow/envs/r.yaml
```

### 3. Provide the hg38 reference genome

Download from [UCSC](https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/) and place under `resources/`:

```bash
# example
wget -P resources/ https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.fa.gz
gunzip resources/hg38.fa.gz
samtools faidx resources/hg38.fa
```

Update `reference.fasta` in `config/config.yaml` if you store it elsewhere.

### 4. Edit `config/config.yaml`

At minimum set:
- `cohort_name` — short name used in output filenames (default: `your_cohort`)
- `input.vcf` — path to your cohort VCF.gz (must have a `.tbi` index alongside)
- `input.has_chr_prefix` — `true` if CHROM column already uses `chr1`/`chrX` style
- `reference.fasta` — path to `hg38.fa`

Optional features (all off by default):
- `relatedness.enabled: true` — run KING kinship filter
- `trio.enabled: true` — split cohort into parents/probands (requires `trio.parents_file`, `trio.probands_file`)
- `merge.tool: plink` — use PLINK 1.9 binary merge instead of bcftools (faster for WGS-scale)
- `annotation.outliers_groups_file` — path to your sample→phenotype TSV for composite-group AFs (§8.3)
- `annotation.outlier_removal_scope` — choose which PCA outliers to remove from the merged VCF: `all`, `cohort_only`, or `reference_only`
- `covariates.macroarea_xlsx` — path to Excel file with `ID` + `MACROAREA` columns for a coloured PCA plot

## Running

```bash
# Dry run (check DAG, no execution)
snakemake -n

# Draw the DAG
snakemake --dag | dot -Tpng > dag.png

# Full run
snakemake --use-conda --cores 4
```

To run on a cluster, add a [Snakemake profile](https://snakemake.readthedocs.io/en/stable/executing/cluster.html) appropriate for your scheduler.

## Outputs

| File | Description |
|---|---|
| `results/normalized/newID_{cohort}.vcf.gz` | Normalized + re-ID'd cohort VCF |
| `results/merge/commonVar_{ref}_{cohort}.vcf.gz` | Merged cohort (≤14832 common variants) |
| `results/pca/commonVar_{ref}_{cohort}.sex.txt` | PCA sex file expanded to merged samples; unknown/reference samples are `SEX=0` |
| `results/pca/pca_commonVar_*.eigenvec` | PCA eigenvectors |
| `results/outliers/outliers_to_remove_{cohort}.txt` | Outlier sample IDs (FID + ID) |
| `results/outliers/outliers_to_remove_{cohort}.samples.txt` | Outlier sample IDs, single-column `bcftools -S` format |
| `results/annotate/groups_{cohort}.txt` | `pca_ita`/`outliers` groups filtered to samples in the annotated cohort VCF |
| `results/outliers/pca_plot_{cohort}.png` | PC1 vs PC2 coloured by outlier status |
| `results/outliers/macroarea_plot_{cohort}.png` | PC1 vs PC2 coloured by MACROAREA *(if covariates supplied)* |
| `results/annotated/groups_INFOtags_{cohort}.vcf.gz` | **Primary deliverable**: VCF with AF, MAF, AF_pca_ita, AF_outliers, etc. |
| `results/merge/no_out_commonVar_*.vcf.gz` | Outlier-free merged VCF *(if remove_outliers_from_merge: true)* |

## Project layout

```
workflow/
├── Snakefile
├── rules/          # one .smk per pipeline section
├── envs/           # conda environment YAMLs
├── scripts/        # R scripts (detect_outliers.R, generate_mixed_groups.R)
└── schemas/        # config.schema.yaml (JSON Schema)
config/
└── config.yaml     # edit this for each run
data/               # input data (unchanged)
resources/          # hg38.fa provided by user
```
