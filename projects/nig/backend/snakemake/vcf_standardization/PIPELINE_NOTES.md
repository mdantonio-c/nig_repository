# NIG VCF Standardization — Pipeline Implementation Notes

## What this pipeline does

Implements the full VCF standardization protocol described in
*Standardizzazione file VCF per piattaforma NIG* (Devito, Hafeez, Casalone, Matullo — UniTo)
as a reproducible Snakemake workflow.

The goal: given a new cohort VCF, normalize it, merge it with the Italian reference cohort
`ITvarGM` (300 samples, 14832 LD-pruned variants), run PCA to identify ancestry outliers,
and produce a final annotated VCF with per-group allele frequencies — the two deliverables
required by the NIG/Cineca/UniTo project:

- `groups_INFOtags_{cohort}.vcf.gz`
- `outliers_mixedgroups.txt` (when phenotypic metadata is available)

---

## Plan (decided before implementation)

### Inputs available
| File | Description |
|---|---|
| `data/test_cohort/test_cohort.vcf.gz` | Test cohort (WES, GATK4, hg38, has `chr` prefix, rsID IDs) |
| `data/ITvarGM.vcf.gz` | Italian reference cohort (300 samples, IDs already `CHROM:POS:REF:ALT`) |
| `data/chr_name_convention.txt` | Maps `1→chr1` etc. |
| `data/no_chr_convention.txt` | Maps `chr1→1` etc. |
| `data/ID_MACROAREA.xlsx` | Optional: sample→geographic macroarea labels (NORD/CENTRO/SUD/SARDEGNA) |

### Key design decisions
1. **hg38 reference**: user-supplied at `resources/hg38.fa` (path in `config.yaml`). No auto-download.
2. **Relatedness filter** (§4): configurable, off by default (`relatedness.enabled: false`).
3. **Trio split** (§7): configurable, off by default (`trio.enabled: false`). When on, requires `parents.txt` and `probands.txt`.
4. **Merge route**: both §5.1 (bcftools) and §5.2 (PLINK binary) implemented; selected via `merge.tool: bcftools|plink`. Default: `bcftools`.
5. **Annotation path**:
   - If `annotation.outliers_groups_file` is empty → §8.2 path: simple `pca_ita`/`outliers` groups only.
   - If provided → §8.3 path: R script expands composite groups (`ita_cardio`, `ita_neuro_male`, etc.).
   - Missing optional inputs → steps that need them are silently skipped.
6. **Macroarea plot**: produced only when `covariates.macroarea_xlsx` is set. For this run: `data/ID_MACROAREA.xlsx`.
7. **Snakemake best practices**: community workflow-template layout, per-rule conda envs, `log:` + `benchmark:` on all rules, config validated against JSON Schema on startup.
8. **Docker**: deferred to next iteration. Conda envs prepared but not created — user does that.

---

## What was implemented

### Directory layout created

```
nig_vcf_stand/
├── workflow/
│   ├── Snakefile                        ← entry point
│   ├── rules/
│   │   ├── common.smk                   ← shared helpers, get_final_targets()
│   │   ├── normalize.smk                ← §3.1 (chr rename + norm + ID rewrite)
│   │   ├── relatedness.smk              ← §4   (KING table + drop related)
│   │   ├── split_trio.smk               ← §7   (parents/probands split)
│   │   ├── merge.smk                    ← §5   (bcftools §5.1 + PLINK §5.2)
│   │   ├── pca.smk                      ← §6   (plink2 make-pgen + PCA)
│   │   ├── outliers.smk                 ← §6.2 (calls detect_outliers.R)
│   │   └── annotate.smk                 ← §8   (fill-tags + §8.4 drop outliers)
│   ├── envs/
│   │   ├── bcftools.yaml                ← bcftools 1.21 + htslib + samtools
│   │   ├── plink.yaml                   ← plink 1.90b7.7 + plink2 2.00a6
│   │   └── r.yaml                       ← R 4.3 + MASS + ggplot2 + dplyr + readxl
│   ├── scripts/
│   │   ├── detect_outliers.R            ← Mahalanobis PCA outlier detection + plots
│   │   └── generate_mixed_groups.R      ← §8.3 composite group expansion
│   └── schemas/
│       └── config.schema.yaml           ← JSON Schema for config validation
├── config/
│   └── config.yaml                      ← all run parameters (edit this per cohort)
├── environment.yaml                     ← Snakemake 8 runner env
├── .gitignore                           ← excludes results/, logs/, hg38.fa
└── README.md                            ← setup + usage instructions
```

### Rule-by-rule summary

#### `normalize.smk` — Section 3.1
- **`add_chr_prefix`** *(conditional on `input.has_chr_prefix: false`)*: `bcftools annotate --rename-chrs no_chr_convention.txt`
- **`normalize_and_reid`**: pipes `bcftools annotate --rename-chrs` → `bcftools norm -f hg38.fa` → `bcftools annotate -x ID -I +'%CHROM:%POS:%REF:%ALT'`
- Output: `results/normalized/newID_{cohort}.vcf.gz` + `.tbi`

For the test cohort (`has_chr_prefix: true`) only `normalize_and_reid` runs.

#### `relatedness.smk` — Section 4
Only in DAG when `relatedness.enabled: true`. Three rules:
- **`king_table`**: `plink2 --make-king-table --king-cutoff 0.088`
- **`related_list`**: strips header from cutoff file (Python `run:` block)
- **`drop_related`**: `bcftools view -S ^related_samples.txt`

`common.smk::get_cohort_vcf_for_merge()` automatically selects the unrelated VCF downstream.

#### `split_trio.smk` — Section 7
Only in DAG when `trio.enabled: true`. Dynamically generates two named rules (`split_trio_parents`, `split_trio_probands`) using a Python loop — avoids copy-paste while keeping Snakemake's rule registry happy.

#### `merge.smk` — Section 5
**bcftools route** (default, §5.1):
- `index_reference` → `common_ids` (bcftools isec) → `extract_common_ref` + `extract_common_cohort` → `merge_cohorts`

**PLINK route** (§5.2):
- `vcf_to_bed_ref` + `vcf_to_bed_cohort` → `common_vars_plink` (Python set intersection on .bim files) → `extract_common_plink_ref` + `extract_common_plink_cohort` → `bmerge` → `plink_to_vcf` (reconvert to VCF.gz for downstream consistency)

Output (either route): `results/merge/commonVar_{ref}_{cohort}.vcf.gz`

#### `pca.smk` — Section 6
- **`prepare_pca_sex_file`**: expands the same sex metadata source used for KING to all merged PCA samples; reference/missing samples are written as `SEX=0`
- **`make_pgen`**: `plink2 --vcf --update-sex --make-pgen` when sex metadata is configured, otherwise `plink2 --vcf --make-pgen`
- **`plink_pca`**: `plink2 --pfile --freq counts --pca allele-wts vcols=chrom,ref,alt`

Pgen files are `temp()` — cleaned up after PCA completes.

#### `outliers.smk` + `detect_outliers.R` — Section 6.2
Single rule using Snakemake `script:` directive so the R script can access `snakemake@input`, `snakemake@output`, `snakemake@params` directly.

The R script:
1. Reads `.eigenvec` (no header — PLINK 2 format), synthesizes column names `FID, ID, PC1..PCN`
2. Mahalanobis distance on first N PCs; threshold = `qchisq(0.999, df=N)`
3. Writes `outliers_to_remove_{cohort}.txt` (FID + ID, no header) — PLINK-compatible
4. Writes `outliers_to_remove_{cohort}.samples.txt` (outlier IDs, single column) — `bcftools -S` compatible
5. Writes `pca_ita_{cohort}.txt` (non-outlier IDs, single column)
6. Saves `pca_plot_{cohort}.png` (PC1 vs PC2, outliers in red)
7. If `macroarea_xlsx` is set: reads Excel, merges on ID, saves `macroarea_plot_{cohort}.png`

#### `annotate.smk` — Section 8
**Path A** (`outliers_groups_file: ""`):
- `filter_pca_groups_to_cohort`: intersects PCA-derived `outliers` and `pca_ita` lists with `bcftools query -l input.vcf`
- `build_groups`: `awk` to produce `groups_{cohort}.txt` with `pca_ita` / `outliers` labels
- `annotate_vcf`: `bcftools +fill-tags -t AN,AC,AC_Hemi,AC_Hom,AC_Het,AF,MAF,NS -S groups.txt`

**Path B** (`outliers_groups_file` set):
- `build_mixed_groups`: calls `generate_mixed_groups.R` which merges user metadata with pipeline-derived `pca_ita`/`outliers` classification, then expands composite groups
- `annotate_vcf`: same command with `outliers_mixedgroups.txt`

`get_groups_file()` helper in `common.smk` routes the `annotate_vcf` rule to the right input transparently.

**§8.4** (`remove_outliers_from_merge: true`):
- `drop_outliers_from_merge`: `bcftools view -S ^outliers_to_remove.samples.txt` on the merged VCF. `annotation.outlier_removal_scope` controls whether the exclusion list is `all`, `cohort_only`, or `reference_only`.

---

## Running the pipeline

### Prerequisites (user must do)

```bash
# 1. Create the Snakemake runner environment
conda env create -f environment.yaml
conda activate snakemake-nig

# 2. Place hg38 reference (or update reference.fasta in config/config.yaml)
wget -P resources/ https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.fa.gz
gunzip resources/hg38.fa.gz
samtools faidx resources/hg38.fa
```

Per-tool conda envs (`bcftools.yaml`, `plink.yaml`, `r.yaml`) are created automatically by Snakemake on first run with `--use-conda`. To pre-build them:
```bash
snakemake --use-conda --conda-create-envs-only
```

### Execute

```bash
# Dry run — check what will run, no execution
snakemake -n

# Draw the DAG
snakemake --dag | dot -Tpng > dag.png

# Full run
snakemake --use-conda --cores 4
```

### Expected outputs for the test cohort run

```
results/normalized/newID_test_cohort.vcf.gz
results/merge/commonVar_ITvarGM_test_cohort.vcf.gz      ← ≤14832 variants
results/pca/pca_commonVar_ITvarGM_test_cohort.eigenvec
results/outliers/outliers_to_remove_test_cohort.txt
results/outliers/pca_ita_test_cohort.txt
results/outliers/pca_plot_test_cohort.png
results/outliers/macroarea_plot_test_cohort.png          ← from ID_MACROAREA.xlsx
results/annotated/groups_INFOtags_test_cohort.vcf.gz    ← PRIMARY DELIVERABLE
results/merge/no_out_commonVar_ITvarGM_test_cohort.vcf.gz
```

### Spot-check commands (from the protocol §8.1.1, §8.3)

```bash
# Verify INFO tags were added
bcftools view -h results/annotated/groups_INFOtags_test_cohort.vcf.gz \
  | grep -E '^##INFO=<ID=(AF|MAF|AN|AF_pca_ita|AF_outliers)'

# Inspect first 5 records
bcftools query \
  -f '%CHROM\t%POS\t%INFO/AF\t%INFO/AF_pca_ita\t%INFO/AF_outliers\n' \
  results/annotated/groups_INFOtags_test_cohort.vcf.gz | head -5

# Variant count in merged VCF (expect ≤14832)
bcftools stats results/merge/commonVar_ITvarGM_test_cohort.vcf.gz \
  | grep "number of records"
```

---

## Configuration reference

All behaviour is driven by `config/config.yaml`. Key options:

| Key | Default | Description |
|---|---|---|
| `cohort_name` | `test_cohort` | Short name used in all output filenames |
| `input.vcf` | test cohort path | Path to input VCF.gz |
| `input.has_chr_prefix` | `true` | Skip chr-rename step if already `chr1` style |
| `reference.fasta` | `resources/hg38.fa` | hg38 reference for `bcftools norm` |
| `relatedness.enabled` | `false` | Run KING kinship filter (§4) |
| `trio.enabled` | `false` | Split cohort into parents/probands (§7) |
| `merge.tool` | `bcftools` | `bcftools` (§5.1) or `plink` (§5.2) |
| `pca.n_components` | `10` | Number of PCs for Mahalanobis distance |
| `pca.mahalanobis_quantile` | `0.999` | Chi² quantile for outlier threshold |
| `annotation.outliers_groups_file` | `""` | If set, run §8.3 composite-group expansion |
| `annotation.remove_outliers_from_merge` | `true` | Produce outlier-free merged VCF (§8.4) |
| `annotation.outlier_removal_scope` | `all` | Which PCA outliers to remove from merged VCF: `all`, `cohort_only`, or `reference_only` |
| `covariates.macroarea_xlsx` | `data/ID_MACROAREA.xlsx` | For macroarea-coloured PCA plot |
| `threads.bcftools` | `4` | Threads for bcftools rules |
| `threads.plink` | `4` | Threads for PLINK rules |

---

## What is NOT in this pipeline (deferred)

- Docker / Apptainer containers
- SLURM / Kubernetes cluster profile
- CI / automated tests
- Auto-download of hg38 reference
- Validation of `outliers_groups_file` column format beyond file existence
