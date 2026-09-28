"""Live contract check against a real Omics environment.

This test is NOT a mocked unit test: it performs a real login (and a couple of
read-only calls) against an actual Omics deployment, to validate assumptions
that cannot be verified from the OpenAPI spec alone (e.g. the exact quota
error shape, HTTP details).

It is skipped by default and never fails a normal test run (local or CI):
it only runs if the required environment variables are set, which must NEVER
be committed to the repository or to `.env`. Export them in your own shell
(``rapydo shell`` does not forward them, ``docker exec -e VAR`` does), e.g.:

    read -rsp "Password Omics: " OMICS_TEST_PASSWORD; echo; export OMICS_TEST_PASSWORD
    export OMICS_TEST_BASE_URL=https://omics.dev2.cineca.it/api/v1/ \\
        OMICS_TEST_USERNAME=<service-account>
    docker exec --user developer -e OMICS_TEST_BASE_URL -e OMICS_TEST_USERNAME \\
        -e OMICS_TEST_PASSWORD -e OMICS_TEST_TASK_ID nig-backend-1 sh -c 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/miniconda3/bin restapi tests --wait --no-destroy --file custom/live/test_omics_live_contract.py'
    unset OMICS_TEST_PASSWORD

No secret is ever printed or asserted into the test output.

Every check is read-only. Observations needed to align NIG with Omics (status
codes, field names, output names; never tokens or passwords) are written to
``OMICS_TEST_REPORT`` (default ``/tmp/omics_live_contract.json``).

Optionally set ``OMICS_TEST_TASK_ID`` to an existing, completed germline task
of the same account: its status and outputs are then checked against what the
fetch task accepts.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

from nig.services.omics import OmicsClient
from nig.services.omics.errors import OmicsAuthError, OmicsError, OmicsRequestError
from nig.tasks.omics_cleanup import _remote_date
from nig.tasks.omics_fetch_results import _expected_outputs

OMICS_TEST_BASE_URL = os.environ.get("OMICS_TEST_BASE_URL")
OMICS_TEST_USERNAME = os.environ.get("OMICS_TEST_USERNAME")
OMICS_TEST_PASSWORD = os.environ.get("OMICS_TEST_PASSWORD")
OMICS_TEST_TASK_ID = os.environ.get("OMICS_TEST_TASK_ID")
REPORT_PATH = Path(
    os.environ.get("OMICS_TEST_REPORT", "/tmp/omics_live_contract.json")
)
# statuses handled by omics_poll_tasks (compared lowercase)
KNOWN_TASK_STATUSES = {"pending", "received", "processing", "complete", "error"}

OBSERVED: Dict[str, Any] = {}

pytestmark = pytest.mark.skipif(
    not (OMICS_TEST_BASE_URL and OMICS_TEST_USERNAME and OMICS_TEST_PASSWORD),
    reason=(
        "OMICS_TEST_BASE_URL / OMICS_TEST_USERNAME / OMICS_TEST_PASSWORD not set: "
        "live Omics contract test skipped (this is expected in CI and in any "
        "run without real service-account credentials)"
    ),
)


@pytest.fixture(scope="module", autouse=True)
def observation_report() -> Iterator[None]:
    yield
    OBSERVED["base_url"] = OMICS_TEST_BASE_URL
    REPORT_PATH.write_text(json.dumps(OBSERVED, indent=2, sort_keys=True, default=str))


@pytest.fixture
def live_client() -> OmicsClient:
    assert OMICS_TEST_BASE_URL is not None
    assert OMICS_TEST_USERNAME is not None
    assert OMICS_TEST_PASSWORD is not None
    return OmicsClient(
        base_url=OMICS_TEST_BASE_URL,
        username=OMICS_TEST_USERNAME,
        password=OMICS_TEST_PASSWORD,
        timeout=30,
    )


def test_live_login_succeeds(live_client: OmicsClient) -> None:
    live_client.authenticate()

    tokens = live_client._auth.tokens
    assert tokens is not None
    assert tokens.access_token
    assert tokens.refresh_token


def test_live_login_with_wrong_password_raises_auth_error() -> None:
    assert OMICS_TEST_BASE_URL is not None
    assert OMICS_TEST_USERNAME is not None
    bad_client = OmicsClient(
        base_url=OMICS_TEST_BASE_URL,
        username=OMICS_TEST_USERNAME,
        password="definitely-not-the-right-password",
        timeout=30,
    )

    with pytest.raises(OmicsAuthError):
        bad_client.authenticate()


def test_live_get_storage_usage_returns_plausible_fields(
    live_client: OmicsClient,
) -> None:
    usage = live_client.get_storage_usage()

    assert isinstance(usage.usage, int)
    assert isinstance(usage.quota, int)
    assert 0 <= usage.limit <= 1
    assert usage.usage >= 0
    assert usage.quota >= 0


def test_live_list_uploaded_files_does_not_error(live_client: OmicsClient) -> None:
    files = live_client.list_uploaded_files()

    assert isinstance(files, list)
    entries = [item for item in files if isinstance(item, dict)]
    OBSERVED["uploaded_files"] = {
        "count": len(files),
        "keys": sorted({key for item in entries for key in item}),
        # the orphan reconciler needs file_id, size and a parseable date
        "missing_file_id": sum(1 for item in entries if not item.get("file_id")),
        "unparseable_date": sum(1 for item in entries if _remote_date(item) is None),
        "sample_date": entries[0].get("date") if entries else None,
    }


def test_live_refresh_token_is_accepted(
    live_client: OmicsClient, monkeypatch: Any
) -> None:
    live_client.authenticate()
    first = live_client._auth.tokens
    assert first is not None

    # refresh() silently falls back to a full login: forbid it to prove the
    # refresh endpoint itself works
    def no_login() -> Any:
        raise AssertionError("refresh_token was refused, fell back to login")

    monkeypatch.setattr(live_client._auth, "login", no_login)
    refreshed = live_client._auth.refresh()

    assert refreshed.access_token
    OBSERVED["refresh"] = {
        "rotates_refresh_token": refreshed.refresh_token != first.refresh_token,
        "token_expiry": refreshed.token_expiry,
    }
    # the refreshed access token is usable
    live_client.get_storage_usage()


def test_live_unknown_task_is_a_request_error(live_client: OmicsClient) -> None:
    missing = str(uuid.uuid4())
    observed: Dict[str, Any] = {}
    for name, call in (
        ("task", live_client.get_task),
        ("task_files", live_client.get_task_files),
    ):
        try:
            result = call(missing)
        except OmicsRequestError as exc:
            observed[name] = {"status_code": exc.status_code}
        except (OmicsError, KeyError, ValueError) as exc:
            observed[name] = {"unexpected": type(exc).__name__}
        else:
            observed[name] = {"unexpected": f"success: {type(result).__name__}"}
    OBSERVED["unknown_task"] = observed

    # poll/fetch isolate a failing dataset only on request errors
    assert all("status_code" in value for value in observed.values()), observed


@pytest.mark.skipif(not OMICS_TEST_TASK_ID, reason="OMICS_TEST_TASK_ID not set")
def test_live_known_task_matches_poll_and_fetch_expectations(
    live_client: OmicsClient,
) -> None:
    assert OMICS_TEST_TASK_ID is not None
    task = live_client.get_task(OMICS_TEST_TASK_ID)
    parameters = task.parameters if isinstance(task.parameters, dict) else {}
    outputs = live_client.get_task_files(OMICS_TEST_TASK_ID)
    OBSERVED["known_task"] = {
        "status": task.status,
        "parameter_keys": sorted(parameters),
        "output_vcf": parameters.get("output_vcf"),
        "outputs": [
            {
                "kind": item.get("_kind"),
                "user_filename": item.get("user_filename"),
                "size": item.get("size"),
                "keys": sorted(item),
            }
            for item in outputs
        ],
    }

    assert task.status.lower() in KNOWN_TASK_STATUSES
    if task.status.lower() == "complete":
        try:
            _expected_outputs(outputs)
        except OmicsError as exc:
            OBSERVED["known_task"]["fetch_rejects"] = str(exc)
            raise
