# NIG Documentation

This documentation describes the existing NIG application, which is based on
RAPyDo 2.4 and its related submodules. Application code normally modified by the
project is located under `projects/nig/`; the content under `submodules/` is
shared framework code.

## Architecture

- [Overview](architecture/overview.md) — project purpose, technology stack, and component interaction.
- [Repository structure](architecture/structure.md) — directory layout, ownership boundaries, and key files.
- [Coding patterns](architecture/patterns.md) — backend, frontend, and testing conventions.

## Development

- [Run, build, test and deploy](development/run-and-build.md) — RAPyDo setup, execution, testing, and deployment.
- [Modification guide](development/modification-guide.md) — entry points for common changes.

## Workflows

- [Application workflows](workflows/workflows.md) — studies, uploads, pipelines, initialization, and asynchronous jobs.

## Security and operations

- [Open questions](security/open-questions.md) — deployment and operational constraints or unknowns.
- [SDCERT-3816 rehearsal report](security/admin-hierarchy-dev-clone-rehearsal.md) — historical evidence from the isolated development clone rehearsal.
- [SDCERT-3816 migration runbook](security/admin-hierarchy-migration-runbook.md) — approved procedure for isolated clone and production migration.

Operational reports, credentials, tokens, database dumps, and rollback artifacts
must not be committed to the repository.
