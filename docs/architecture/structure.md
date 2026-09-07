# Repository Structure

_Confirmed by directory listing + spot reads. Only `projects/nig/` is normally edited._

```
nig-repository/
├── docker-compose.yml          # RAPyDo-generated snapshot; currently proxy-only
├── .env                        # RAPyDo-generated runtime env vars (DO NOT COMMIT SECRETS)
├── data/                       # host-mounted volumes
│   ├── data/{input,output,jobs,resources_for_db_setup}/
│   ├── graphdata/               # Neo4j data files
│   ├── logs/                    # backend-server.log, security-events.log, mock mail
│   └── nig/{cypress,frontend,karma}/  # frontend test artifacts
├── docs/security/              # security procedures and operational runbooks
├── projects/nig/                # <-- THE APPLICATION CODE (main edit target)
│   ├── project_configuration.yaml  # real RAPyDo project config (roles, env, tags)
│   ├── backend/
│   │   ├── endpoints/            # Flask REST endpoints (auto-discovered by RAPyDo)
│   │   │   └── admin_users.py     # in-place Root/Staff guard for framework admin API
│   │   ├── models/neo4j.py       # Neomodel graph schema (Study, Dataset, File, ...)
│   │   ├── services/              # domain/security policy helpers
│   │   │   ├── admin_policy.py    # Root/Staff authorization and integrity invariants
│   │   │   └── admin_security.py  # redacted audit records and best-effort notifications
│   │   ├── tasks/                # Celery tasks (launch_pipeline, launch_joint_analysis)
│   │   ├── snakemake/            # *.smk workflow files + config.yaml
│   │   ├── cron/                 # analysis_management.cron (triggers pipeline every ~8h)
│   │   ├── scripts/               # init plus operational scripts
│   │   │   ├── precheck_admin_hierarchy.py  # standalone read-only Neo4j inventory
│   │   │   └── migrate_admin_hierarchy.py   # dry-run/apply/rollback Root/Staff migration
│   │   ├── initialization.py     # startup GeoData import and conditional Root integrity gate
│   │   ├── customization.py      # RAPyDo customization hook point
│   │   └── tests/                # pytest suite (tests/custom equivalent for NIG)
│   ├── builds/backend/Dockerfile # backend image build (Conda + GATK/BWA/samtools)
│   ├── confs/                    # RAPyDo config templates
│   └── frontend/
│       ├── app/
│       │   ├── components/       # studies, study, stats, stats-details, welcome
│       │   ├── services/data.service.ts  # centralized HTTP calls via ApiService
│       │   ├── custom.module.ts  # routing + NgModule wiring
│       │   └── customization.ts  # RAPyDo Angular customization hook
│       ├── assets/, styles/, e2e/ (Cypress)
│       └── package.json
├── submodules/                   # RAPyDo framework + CLI — do not edit
│   ├── http-api/                 # Flask backend framework (restapi.*)
│   ├── rapydo-angular/           # Angular base (ApiService, AuthGuard, @rapydo/*)
│   ├── build-templates/          # Docker image templates for all services
│   ├── do/                       # the `rapydo` CLI (controller/)
│   └── quality-checks/           # juan.qc.* QC classes used post-pipeline
└── .github/
    ├── copilot-instructions.md   # agent-facing project notes
    ├── agents/                   # custom agent definitions
    └── workflows/                # GitHub Actions CI
```

## Key file index (quick lookup)

| What | Path |
|------|------|
| Backend endpoint base class | `projects/nig/backend/endpoints/__init__.py` |
| Studies CRUD | `projects/nig/backend/endpoints/study.py` |
| Datasets CRUD | `projects/nig/backend/endpoints/dataset.py` |
| File upload | `projects/nig/backend/endpoints/files.py` |
| Phenotypes | `projects/nig/backend/endpoints/phenotypes.py` |
| Technical metadata | `projects/nig/backend/endpoints/tech_metadata.py` |
| HPO search | `projects/nig/backend/endpoints/hpo.py` |
| Download | `projects/nig/backend/endpoints/download.py` |
| Family relationships | `projects/nig/backend/endpoints/family.py` |
| Admin stats | `projects/nig/backend/endpoints/admin_server_stats.py`, `projects/nig/backend/endpoints/stats.py` |
| Admin-user hierarchy override | `projects/nig/backend/endpoints/admin_users.py`, `projects/nig/backend/services/admin_policy.py`, `projects/nig/backend/services/admin_security.py` |
| Hierarchy pre-check/migration | `projects/nig/backend/scripts/precheck_admin_hierarchy.py`, `projects/nig/backend/scripts/migrate_admin_hierarchy.py` |
| Neo4j models | `projects/nig/backend/models/neo4j.py` |
| Pipeline launch task | `projects/nig/backend/tasks/launch_pipeline.py` |
| Joint analysis task | `projects/nig/backend/tasks/launch_joint_analysis.py` |
| Snakemake single-sample workflow | `projects/nig/backend/snakemake/Single_Sample.smk` |
| Snakemake joint-samples workflow | `projects/nig/backend/snakemake/Joint_samples.smk` |
| Startup initializer (GeoData) | `projects/nig/backend/initialization.py` |
| Cron trigger | `projects/nig/backend/cron/analysis_management.cron` |
| Pipeline trigger script | `projects/nig/backend/scripts/init_pipeline.py` |
| HPO loader script | `projects/nig/backend/scripts/init_hpo.sh`, `projects/nig/backend/scripts/parsing_hpo.py` |
| Backend tests | `projects/nig/backend/tests/` |
| Hierarchy tests | `projects/nig/backend/tests/test_admin_policy.py`, `projects/nig/backend/tests/test_api_admin_hierarchy.py`, `projects/nig/backend/tests/test_admin_hierarchy_scripts.py` |
| Frontend routing | `projects/nig/frontend/app/custom.module.ts` |
| Frontend components | `projects/nig/frontend/app/components/` |
| Frontend data service | `projects/nig/frontend/app/services/data.service.ts` |
| Project config (real) | `projects/nig/project_configuration.yaml` |
| Generated compose snapshot | `docker-compose.yml` |
