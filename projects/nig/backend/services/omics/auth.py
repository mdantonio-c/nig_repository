"""Omics authentication: login and transparent token refresh.

The NIG service account has OTP disabled in Keycloak, so no OTP field is ever
sent. Credentials and tokens are never logged.
"""

from typing import Dict, Optional

from restapi.utilities.logs import log

from nig.services.omics.errors import OmicsAuthError
from nig.services.omics.models import TokenPair


class OmicsAuth:
    def __init__(
        self,
        session: object,
        base_url: str,
        username: str,
        password: str,
        timeout: int,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._tokens: Optional[TokenPair] = None

    @property
    def tokens(self) -> Optional[TokenPair]:
        return self._tokens

    def login(self) -> TokenPair:
        response = self._session.post(  # type: ignore[attr-defined]
            self._url("login"),
            json={"username": self._username, "password": self._password},
            timeout=self._timeout,
        )
        if response.status_code != 200:
            detail = ""
            try:
                detail = str(response.json().get("detail", ""))
            except (ValueError, AttributeError):
                pass
            message = f"Omics login failed with status {response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise OmicsAuthError(message)
        payload = response.json()
        self._tokens = TokenPair(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            token_expiry=payload.get("token_expiry"),
        )
        log.info("Authenticated to Omics service account")
        return self._tokens

    def refresh(self) -> TokenPair:
        if self._tokens is None:
            return self.login()

        response = self._session.post(  # type: ignore[attr-defined]
            self._url("refresh_token"),
            json={"refresh_token": self._tokens.refresh_token},
            timeout=self._timeout,
        )
        if response.status_code != 200:
            log.warning("Omics token refresh failed, falling back to full login")
            return self.login()

        payload = response.json()
        self._tokens = TokenPair(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token", self._tokens.refresh_token),
            token_expiry=payload.get("token_expiry"),
        )
        return self._tokens

    def auth_header(self) -> Dict[str, str]:
        if self._tokens is None:
            self.login()
        assert self._tokens is not None
        return {"Authorization": f"Bearer {self._tokens.access_token}"}

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"
