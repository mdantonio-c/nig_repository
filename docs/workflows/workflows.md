# Key End-to-End Workflows

## 1. Study → Dataset → File upload

1. User creates a Study: `POST /api/study` → `Studies` endpoint
   (`projects/nig/backend/endpoints/study.py`) validates via
   `StudyInputSchema`, creates a `Study` node (`projects/nig/backend/models/neo4j.py`).
2. User creates a Dataset under the study:
   `projects/nig/backend/endpoints/dataset.py` (`/api/study/<uuid>/datasets`) — creates `Dataset` node,
   linked to `Study` via `CONTAINS`.
3. User uploads FASTQ files: `projects/nig/backend/endpoints/files.py`
   (`/api/dataset/<uuid>/files/upload`) — stores at
   `/data/input/{group_uuid}/{study_uuid}/{dataset_uuid}/{filename}`. Filenames must match
   `SampleName_R1.fastq.gz` / `SampleName_R2.fastq.gz`.

## 2. Pipeline trigger → variant calling (single sample)

```
Cron (every ~8h, projects/nig/backend/cron/analysis_management.cron)
  → projects/nig/backend/scripts/init_pipeline.py            (selects datasets ready to run)
  → Celery task projects/nig/backend/tasks/launch_pipeline.py:launch_pipeline(dataset_list, snakefile, force)
       1. Create `Job` node keyed by Celery task UUID
       2. Create workdir /data/jobs/<task_id>/, copy snakemake/*.smk + config.yaml into it
       3. For each dataset: resolve group/study/dataset uuids, locate FASTQ files, validate naming pattern
          - if invalid/missing R1 → dataset.status = "ERROR", connects Dataset→Job
            edge with error_message
          - else → dataset.status = "RUNNING", connects Dataset→Job edge
       4. Build fastq.csv (Sample, Frag, InputPath, OutputPath, Reverse)
       5. Symlink /data/input/... → /data/output/... locations as needed
       6. Call snakemake(snakefile="Single_Sample.smk", ...)
       7. Check tool/version-sensitive logs via `juan.qc.*` classes; update dataset and
          JobRelation to COMPLETED/ERROR; synchronously send an admin email on failure
  → Pipeline steps (projects/nig/backend/snakemake/Single_Sample.smk): Fastqc → Seqtk (Q33) →
    BwaP/BwaS (alignment) → Samblaster (mark dup) → Samsort → Samindex →
    BaseRecalibrator → ApplyBQSR → HaplotypeCaller → Rename
  → Final output: /data/output/{group}/{study}/{dataset}/gatk_gvcf/{sample}_sort_nodup.g.vcf.gz
```

Dataset status flow:
`(file uploaded) → "UPLOAD COMPLETED"` (user-triggered) `→ "QUEUED"` (cron-triggered) `→ "RUNNING"` `→ "COMPLETED"` or `"ERROR"`.

## 3. Joint analysis (multi-sample)

`projects/nig/backend/scripts/init_joint_analysis.py` selects completed datasets using the `UPDATE.GDBI`
marker and dispatches `projects/nig/backend/tasks/launch_joint_analysis.py`.
The task creates a `JointAnalysisJob`, writes a multi-dataset `fastq.csv`, sets
`Dataset.joint_analysis = True`, and runs `projects/nig/backend/snakemake/Joint_samples.smk`:
GenomicsDBImport → GenotypeGVCFs → VariantFiltration.

## 4. Backend startup initialization

On every backend container start, RAPyDo calls `projects/nig/backend/initialization.py`:`Initializer.__init__`:
- Reads `/data/resources_for_db_setup/geodata.tsv`, upserts `GeoData` nodes in Neo4j.
- **HPO data is NOT auto-loaded here** — must be run manually/in CI via
  `projects/nig/backend/scripts/init_hpo.sh`.

## 5. CI backend pipeline

`.github/workflows/github_actions-backend.yml`:
`rapydo install` → `rapydo build` → `rapydo start` (with SMTP mock env vars and
`AUTH_LOGIN_BAN_TIME=10`) → wait for backend → run `init_hpo.sh` and
`restapi tests --wait --destroy`, **both explicitly using a system-first PATH**
(`/usr/local/sbin:...:/opt/miniconda3/bin`) to avoid Conda's Python shadowing the system Python.

## 6. Password reset behavior

The route is framework-owned but its POST method is NIG-overridden in `projects/nig/backend/endpoints/reset_password.py`:
For every syntactically valid address, eligible success, unknown/ineligible account
and expected SMTP failure return the same neutral `200` response. Only an eligible account
with successful mail gets a persisted reset token.

## 7. Chunk upload and download

- **Upload**: Browser initializes with metadata (`201`, empty body and `Location`),
   then sends raw PUT chunks with `Content-Range`. Partial uploads return `206`,
   `partial` and `Range`; completion validates expected size, gzip/text/FASTQ
   structure and paired-end naming, then stores final files with mode `0440`.
- **Download**: The completed-dataset download streams in 1 MiB chunks with
   `Content-Disposition` and `Content-Length`; the size option returns the physical
   byte count rather than a stream.

## 8. Root/Staff administrative hierarchy

The merged SDCERT-3816 change partitions the inherited administrative role into an
immutable Root and operational Staff:
- Root is the configured default user that alone has `admin_root`; it must be active,
  unexpired and have no other roles. Root remains immutable through the API.
- Staff can create accounts and manage non-Staff users.
- Role changes revoke the target's tokens.
- Startup and the endpoint gate fail closed in production when the invariant fails.

For existing graphs, use the standalone read-only pre-check first, then dry-run,
approved apply, post-check/idempotence dry-run, and only approved rollback via
`projects/nig/backend/scripts/`.

The controlled procedure and the separate rehearsal evidence are in
`docs/security/`; do not repair role graphs from HTTP handlers or manually in
Neo4j.

## 9. Persistence and backup boundary

Neo4j records and the mounted `/data/input`, `/data/output` and `/data/jobs`
trees form one logical datastore. A Neo4j dump alone is not a complete backup or
rollback point for NIG: dataset/file records and statuses refer to physical files.
Operations that require recovery must coordinate the graph and filesystem snapshot.
