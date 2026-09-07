# Architectural & Coding Patterns

## Backend: RAPyDo endpoint pattern

Endpoints are plain classes that RAPyDo **auto-discovers**.
Every NIG endpoint extends `NIGEndpoint` (`projects/nig/backend/endpoints/__init__.py`).

```python
class Studies(NIGEndpoint):
    labels = ["study"]

    @decorators.auth.require()
    @decorators.endpoint(path="/study", summary="...", responses={200: "..."})
    @decorators.marshal_with(StudyOutput(many=True), code=200)
    def get(self, user: User) -> Response:
        ...
```

- Input validation: Marshmallow `Schema` subclasses + `@decorators.use_kwargs(...)`.
- Output serialization: `@decorators.marshal_with(SomeOutputSchema, code=200)`.
- Auth: `@decorators.auth.require()`.
- Not-found/permission errors centralized as string constants in `projects/nig/backend/endpoints/__init__.py`.

## Backend: data model = source of truth

All domain entities and relationships live in Neo4j via Neomodel (`projects/nig/backend/models/neo4j.py`).
**Convention**: do not introduce a parallel persistence layer (e.g. SQL/Postgres is present in the stack but disabled).

## Backend: Celery task pattern

Tasks are decorated with `@CeleryExt.task(idempotent=True, autoretry_for=(...))`.
Tasks create a `Job` node in Neo4j keyed by the Celery task UUID, then connect it to
the relevant `Dataset` nodes via the relationship, giving traceability.

## Backend: schema-driven forms

NgxFormly generates frontend forms directly from Marshmallow schemas:
- `validate.OneOf([...])` on a schema field → renders as a `<select>` dropdown.
- `autocomplete_endpoint` field metadata → renders an autocomplete widget.
- **Convention**: prefer changing the backend schema first for form changes.

## Backend: path mapping convention

Container paths (`/data`, `/resources`, `/snakemake`) are referenced via `restapi.config.DATA_PATH` and
`INPUT_ROOT`/`OUTPUT_ROOT` constants in `projects/nig/backend/endpoints/__init__.py`.

## Frontend: component/service conventions

- All HTTP calls funnel through `ApiService`, centralized per-domain in
  `projects/nig/frontend/app/services/data.service.ts`.
- Routing + module wiring lives in `projects/nig/frontend/app/custom.module.ts`.
- Components under `projects/nig/frontend/app/components/` are one folder per route/tab.

## Testing conventions

- One `test_api_<domain>.py` file per endpoint group under `projects/nig/backend/tests/`.
- Use the NIG `test_env` pytest fixture for exception-safe setup/cleanup.
- `projects/nig/backend/tasks/test_task.py` is RAPyDo test infrastructure, not NIG business logic.

## Error handling / logging

- Errors: `restapi.exceptions` (`BadRequest`, `NotFound`, `Conflict`, ...) raised
  directly from endpoint methods.
- Logging: `restapi.utilities.logs.log` (loguru-based).

## Framework endpoint override pattern (RAPyDo 2.4 only)

Some framework-owned endpoints require a module-import-time replacement of a
method on the already-loaded core class. This is a narrow, version-sensitive
exception: do not register a second endpoint class for the same method and path.
Keep route and OpenAPI uniqueness tests whenever an inherited endpoint is
overridden.

## Root/Staff policy override (RAPyDo 2.4 only)

The administration hierarchy uses the same loader-sensitive method-replacement
technique, but replaces `AdminUsers.post`, `put`, and `delete` in `projects/nig/backend/endpoints/admin_users.py`.

- Keep authorization decisions pure and centralized in `projects/nig/backend/services/admin_policy.py`.
- Reuse core persistence only after policy validation.
- Keep graph repair out of request handlers. Use `projects/nig/backend/scripts/migrate_admin_hierarchy.py`.

## Security logging and rate limiting

- Structured audit events are written to `/logs/security-events.log`.
- Production NGINX applies rate limits to authentication endpoints. Preserve the
  generated proxy configuration and verify rate-limit behavior through the proxy,
  not the direct backend port.
