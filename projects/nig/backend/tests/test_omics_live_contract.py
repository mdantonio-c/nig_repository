"""Live contract check against a real Omics environment.

This test is NOT a mocked unit test: it performs a real login (and a couple of
read-only calls) against an actual Omics deployment, to validate assumptions
that cannot be verified from the OpenAPI spec alone (e.g. the exact quota
error shape, HTTP details).

It is skipped by default and never fails a normal test run (local or CI):
it only runs if the required environment variables are set, which must NEVER
be committed to the repository or to `.env`. Provide them inline on the
command used to invoke the test run, e.g.:

    OMICS_TEST_BASE_URL="https://omics.dev2.cineca.it/api/v1/" \\
    OMICS_TEST_USERNAME="<service-account-username>" \\
    OMICS_TEST_PASSWORD="<service-account-password>" \\
    rapydo shell backend 'sh -c "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/miniconda3/bin restapi tests --wait --no-destroy --file custom/test_omics_live_contract.py"'

No secret is ever printed or asserted into the test output.
"""

import os

import pytest

from nig.services.omics import OmicsClient
from nig.services.omics.errors import OmicsAuthError

OMICS_TEST_BASE_URL = os.environ.get("OMICS_TEST_BASE_URL")
OMICS_TEST_USERNAME = os.environ.get("OMICS_TEST_USERNAME")
OMICS_TEST_PASSWORD = os.environ.get("OMICS_TEST_PASSWORD")

pytestmark = pytest.mark.skipif(
    not (OMICS_TEST_BASE_URL and OMICS_TEST_USERNAME and OMICS_TEST_PASSWORD),
    reason=(
        "OMICS_TEST_BASE_URL / OMICS_TEST_USERNAME / OMICS_TEST_PASSWORD not set: "
        "live Omics contract test skipped (this is expected in CI and in any "
        "run without real service-account credentials)"
    ),
)


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
