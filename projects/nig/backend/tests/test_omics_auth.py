"""Unit tests for :mod:`nig.services.omics.auth`.

Uses a fake HTTP session (no real network, no ``responses``/``requests_mock``
dependency) that only implements the small ``.post()`` surface used by
:class:`OmicsAuth`.
"""

import pytest

from nig.services.omics.auth import OmicsAuth
from nig.services.omics.errors import OmicsAuthError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, responses):
        # `responses` is a list of FakeResponse consumed in order by .post()
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        return self._responses.pop(0)


def _auth(session) -> OmicsAuth:
    return OmicsAuth(
        session=session,
        base_url="https://omics.dev.cineca.it/api/v1/",
        username="nig-service",
        password="s3cr3t",
        timeout=30,
    )


def test_login_success_stores_tokens_and_never_logs_password() -> None:
    session = FakeSession(
        [FakeResponse(200, {"access_token": "AT1", "refresh_token": "RT1"})]
    )
    auth = _auth(session)

    tokens = auth.login()

    assert tokens.access_token == "AT1"
    assert tokens.refresh_token == "RT1"
    # the request body sent must not contain an 'otp' field (OTP disabled for
    # the NIG service account, plan section 2.1)
    _, body, _ = session.calls[0]
    assert "otp" not in body
    assert body == {"username": "nig-service", "password": "s3cr3t"}


def test_login_failure_raises_omics_auth_error() -> None:
    session = FakeSession([FakeResponse(401, {})])
    auth = _auth(session)

    with pytest.raises(OmicsAuthError):
        auth.login()


def test_refresh_uses_refresh_token_and_updates_access_token() -> None:
    session = FakeSession(
        [
            FakeResponse(200, {"access_token": "AT1", "refresh_token": "RT1"}),
            FakeResponse(200, {"access_token": "AT2", "refresh_token": "RT2"}),
        ]
    )
    auth = _auth(session)
    auth.login()

    tokens = auth.refresh()

    assert tokens.access_token == "AT2"
    assert tokens.refresh_token == "RT2"
    refresh_url, refresh_body, _ = session.calls[1]
    assert refresh_body == {"refresh_token": "RT1"}


def test_refresh_without_prior_login_performs_full_login() -> None:
    session = FakeSession(
        [FakeResponse(200, {"access_token": "AT1", "refresh_token": "RT1"})]
    )
    auth = _auth(session)

    tokens = auth.refresh()

    assert tokens.access_token == "AT1"
    assert len(session.calls) == 1


def test_refresh_failure_falls_back_to_full_login() -> None:
    session = FakeSession(
        [
            FakeResponse(200, {"access_token": "AT1", "refresh_token": "RT1"}),
            FakeResponse(401, {}),
            FakeResponse(200, {"access_token": "AT2", "refresh_token": "RT2"}),
        ]
    )
    auth = _auth(session)
    auth.login()

    tokens = auth.refresh()

    assert tokens.access_token == "AT2"
    assert len(session.calls) == 3


def test_auth_header_triggers_login_if_no_token_yet() -> None:
    session = FakeSession(
        [FakeResponse(200, {"access_token": "AT1", "refresh_token": "RT1"})]
    )
    auth = _auth(session)

    header = auth.auth_header()

    assert header == {"Authorization": "Bearer AT1"}
