# Open Questions / Deployment Unknowns / Decisions

## Deployment and operational questions

1. **[deployment unknown, blocker]** What Neo4j version, edition, image digest, store format and database size are actually deployed?
2. **[deployment unknown, blocker]** Provide a sanitized `docker compose config` (or equivalent generated production manifest).
3. **[deployment unknown, blocker]** What backup/SLA/RPO/RTO policy exists, and has a coordinated Neo4j + filesystem restore ever been tested?
4. **[deployment unknown]** Which RAPyDo features are enabled in the deployed configuration?
5. **[deployment unknown]** Is joint analysis currently scheduled or manually used?
6. **[deployment unknown]** Are there external API clients beyond the Angular UI?
7. **[data profiling required]** Do production relations satisfy assumed cardinalities?
8. **[security/operations]** Confirm audit-log retention and SMTP recipient logging.

## Discrepancies found vs. `.github/copilot-instructions.md`

- **Dataset status flow**: Confirmed correct. `UPLOAD COMPLETED → QUEUED → RUNNING → COMPLETED / ERROR`.
- **CI PATH fix**: Confirmed already implemented in GitHub Actions.
- **GitLab vs. GitHub**: GitHub Actions are a legacy mirror. A proper `.gitlab-ci.yml` is a tracked future item.
- **Test migration**: All 9 custom tests fully migrated to the `test_env` fixture.

## SDCERT-3816 Root/Staff hierarchy

- **[confirmed, merged into `dev`]** Merge commit `98167e9f` on 2026-09-04.
- **[test-confirmed]** Targeted policy, API, and migration-script tests are present.
- **[compatibility decision needed]** Inherited RAPyDo tests still encode the old contract.
- **[security/operations]** Confirm recipient/audit-log retention and production deployment procedure.

## Confirmed discrepancies and hazards

- Root `docker-compose.yml` is a generated proxy-only snapshot.
- No root `project_configuration.yaml` or `.gitmodules` exists.
- HPO setup is manual/CI-only.
- Joint analysis has relation/status/activation ambiguities.
- `VariantRelation.DP` is declared twice.
- NIG-specific browser e2e tests are absent.
- Current CI is a legacy GitHub mirror.
