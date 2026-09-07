# Run, Build, Test, Deploy

## Local setup

Prerequisites: Python 3.8+, Docker 20+ with Compose v2, Git.

```bash
git clone https://gitlab.hpc.cineca.it/nig/nig-repository.git
cd nig-repository
git checkout 2.4

sudo pip3 install --upgrade git+https://github.com/rapydo/do.git@2.4
rapydo install

rapydo init
rapydo pull
rapydo build
rapydo start
```

Dev mode requires manually launching the API:
```bash
rapydo shell backend "restapi launch"
```

## Path mapping (container ↔ host)

| Inside container | Host path (relative to repo root) |
|---|---|
| `/data` | `data/data/` |
| `/data/input/` | `data/data/input/` |
| `/data/output/` | `data/data/output/` |
| `/data/jobs/` | `data/data/jobs/` |
| `/resources/` | `data/resources/` |
| `/code/nig/` | `projects/nig/backend/` |
| `/snakemake/` | `projects/nig/backend/snakemake/` |

## Backend tests

**Verified baseline**: 101 passed, 10 skipped.

Run the suite through `restapi tests --wait --destroy`, not with ad-hoc `pytest`.
The RAPyDo runner configures Docker-network aliases required by Neo4j, Redis and
the SMTP mock. NIG API tests use the `test_env` yield fixture for exception-safe,
idempotent graph and filesystem cleanup; new tests should use the same fixture.

Critical environment detail: the container's default `PATH` puts **Conda first**.
Use a **system-first PATH** only for HPO loading and running tests:
```bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/miniconda3/bin
```

Required SMTP mock values for tests:
```
SMTP_HOST=mock.mail.service
SMTP_PORT=0
SMTP_ADMIN=mock@nomail.org
SMTP_NOREPLY=mock@nomail.org
```

Manual local run:
```bash
rapydo shell backend "sh -c 'PATH=$SYS_PATH bash nig/scripts/init_hpo.sh'"
rapydo shell backend "sh -c 'PATH=$SYS_PATH restapi tests --wait --destroy'"
```

The test environment also requires `AUTH_LOGIN_BAN_TIME=10`; otherwise deliberate
failed-login tests can block the default administrator for the normal 12-hour
period and cause cascading failures. For an interrupted test run, recover with
`restapi forced-clean`, then `restapi init --wait --force-user --force-group`,
reload HPO with the system-first `PATH`, and rerun the suite.

## Manual pipeline test/dry-run

```bash
rapydo shell celery
snakemake --snakefile /snakemake/Single_Sample.smk --cores 1 \
  --directory /data/jobs/test_debug --configfiles /snakemake/config.yaml \
  --forceall --printshellcmds --debug-dag --dry-run --verbose --debug -p
```

## CI (GitHub Actions)

Workflows in `.github/workflows/`:
- `github_actions-backend.yml` — `rapydo install/build/start` → wait → run
  `init_hpo.sh` and `restapi tests --wait --destroy` using the system-first `PATH`.
- `github_actions-frontend.yml` — RAPyDo-driven Karma tests and production frontend build.
- `github_actions-cypress.yml` — inherited RAPyDo Cypress suite.

GitHub Actions is a legacy mirror used for CI. The canonical repository remote is
GitLab; a reliable repository-managed GitLab pipeline remains a future task.

## Deployment

Manual via `rapydo` CLI:
```bash
rapydo install
rapydo init
rapydo pull
rapydo build
rapydo start
```

### Root/Staff hierarchy migration

Do not modify administrative role edges manually. Use the approved process:
1. Deploy backend policy.
2. Isolated clone rehearsal.
3. Read-only `precheck_admin_hierarchy.py`.
4. Reviewed `migrate_admin_hierarchy.py --dry-run`.
5. Approved apply.
6. Post-check and idempotence dry-run.
