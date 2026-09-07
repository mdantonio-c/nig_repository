# Modification Guide — "If you want to change X, start here"

## General rules

- Work surgically inside `projects/nig/backend/` and `projects/nig/frontend/`.
- Do not edit `submodules/` unless explicitly requested.
- Neo4j is the single source of truth for domain data.
- Keep style/conventions consistent with existing files (see `docs/architecture/patterns.md`).

## Add/change a REST endpoint

1. Add or edit a class extending `NIGEndpoint` in `projects/nig/backend/endpoints/`.
2. Define/adjust Marshmallow schemas for input (`use_kwargs`) and output (`marshal_with`).
3. Add auth via `@decorators.auth.require()`.
4. Add a matching test in `projects/nig/backend/tests/test_api_<domain>.py`.

## Change administrative users, Root/Staff policy, or its migration

Start with `projects/nig/backend/services/admin_policy.py`, then the inherited-method override in `projects/nig/backend/endpoints/admin_users.py`.

1. Treat `admin_root` as migration-only.
2. Keep authorization and field matrices in `admin_policy.py`.
3. Retain the core endpoint call after validation and the explicit wrapping/route uniqueness tests.
4. Change existing role graphs only through the pre-check/dry-run/apply/rollback tooling in `projects/nig/backend/scripts/`.

## Add/change a Neo4j model field

1. Edit `projects/nig/backend/models/neo4j.py`.
2. Update the relevant endpoint's input/output schema to expose the new field.
3. If the field should drive a form, prefer schema-level `validate.OneOf([...])` or `autocomplete_endpoint` metadata.

## Add a new pipeline / Snakemake workflow

1. Add the `.smk` file under `projects/nig/backend/snakemake/`.
2. Branch on the trigger condition inside `projects/nig/backend/tasks/launch_pipeline.py`.
3. Update `projects/nig/backend/snakemake/config.yaml` if new reference files/params are needed.
4. Verify with a Snakemake dry-run.

### Genome studies

`study_type` is the prerequisite for genome-specific UI and pipeline work. Add it
to the `Study` model and study input/output schemas before adding a genome tab or
branching pipeline selection.

## Frontend: add/change a form or component

1. If the field is schema-driven, change the backend schema first.
2. For UI-only changes, add a component under `projects/nig/frontend/app/components/` and wire it into `projects/nig/frontend/app/custom.module.ts`.
3. Route all new HTTP calls through `projects/nig/frontend/app/services/data.service.ts`.

## Gotchas

- Reuse container path constants (`INPUT_ROOT`, `OUTPUT_ROOT`, `DATA_PATH`) defined in `projects/nig/backend/endpoints/__init__.py`.
- FASTQ filenames must match `SampleName_R1.fastq.gz` / `_R2.fastq.gz` — this regex is duplicated in both the upload endpoint and `launch_pipeline.py`.
- Running backend tests or `init_hpo.sh` with the container's default `PATH` will fail — always use the system-first `PATH` override.
- `projects/nig/backend/tasks/test_task.py` is Celery test infrastructure. Do not
	treat it as pipeline logic or ask RAPyDo to create it again in CI when it is
	already versioned.
