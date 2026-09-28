from datetime import datetime, timedelta
from typing import Any, List

import pytest
import pytz
from faker import Faker
from nig.endpoints.reset_password import RESET_RESPONSE
from nig.tests import TestEnv, test_env  # noqa: F401
from restapi.connectors import Connector
from restapi.endpoints.reset_password import RecoverPassword
from restapi.exceptions import Forbidden, ServiceUnavailable
from restapi.tests import API_URI, AUTH_URI, BaseTests, FlaskClient
from restapi.utilities.logs import OBSCURE_VALUE, handle_log_output


class TestApp(BaseTests):
    @staticmethod
    def _reset_tokens(auth: Any, user: Any) -> List[Any]:
        return [
            token
            for token in auth.get_tokens(user=user)
            if token.get("token_type") == auth.PWD_RESET
        ]

    def test_password_reset_is_non_enumerating(
        self,
        client: FlaskClient,
        faker: Faker,
        monkeypatch: pytest.MonkeyPatch,
        test_env: TestEnv,  # noqa: F811
    ) -> None:
        (
            _,
            _,
            user_uuid,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
        ) = test_env.setup(study=False)

        auth = Connector.get_authentication_instance()
        user = auth.get_user(user_id=user_uuid)
        assert user is not None
        request_data = {"reset_email": user.email.upper()}

        # Eligible account: neutral response, email and persisted reset token.
        self.delete_mock_email()
        active_response = client.post(f"{AUTH_URI}/reset", json=request_data)
        assert active_response.status_code == 200
        assert self.get_content(active_response) == RESET_RESPONSE
        active_body = active_response.data
        active_content_type = active_response.headers["Content-Type"]

        mail = self.read_mock_email()
        token = self.get_token_from_body(mail.get("body", ""))
        assert token is not None
        assert len(self._reset_tokens(auth, user)) == 1

        # The inherited framework PUT remains operational and one-time only.
        new_password = faker.password(auth.MIN_PASSWORD_LENGTH + 4, strong=True)
        password_data = {
            "new_password": new_password,
            "password_confirm": new_password,
        }
        response = client.put(
            f"{AUTH_URI}/reset/{token}", json=password_data
        )
        assert response.status_code == 200
        assert self._reset_tokens(auth, user) == []
        response = client.put(f"{AUTH_URI}/reset/{token}", json={})
        assert response.status_code == 400
        assert self.get_content(response) == "Invalid reset token"

        def assert_neutral(response: Any) -> None:
            assert response.status_code == 200
            assert response.data == active_body
            assert response.headers["Content-Type"] == active_content_type
            assert self.get_content(response) == RESET_RESPONSE
            with pytest.raises(FileNotFoundError):
                self.read_mock_email()

        # Unknown account: no email, token or externally observable distinction.
        self.delete_mock_email()
        unknown_response = client.post(
            f"{AUTH_URI}/reset", json={"reset_email": faker.ascii_email()}
        )
        assert_neutral(unknown_response)

        # Inactive account.
        user.is_active = False
        auth.save_user(user)
        self.delete_mock_email()
        inactive_response = client.post(f"{AUTH_URI}/reset", json=request_data)
        assert_neutral(inactive_response)
        assert self._reset_tokens(auth, user) == []
        user.is_active = True
        auth.save_user(user)

        # Expired account.
        user.expiration = datetime.now(pytz.utc) - timedelta(minutes=1)
        auth.save_user(user)
        self.delete_mock_email()
        expired_response = client.post(f"{AUTH_URI}/reset", json=request_data)
        assert_neutral(expired_response)
        assert self._reset_tokens(auth, user) == []
        user.expiration = None
        auth.save_user(user)

        # Temporarily blocked account. The framework status check emits its audit
        # event; the custom handler must suppress only the external distinction.
        self.delete_mock_email()

        def raise_blocked(_auth: Any, _username: str) -> None:
            raise Forbidden("blocked")

        with monkeypatch.context() as patch:
            patch.setattr(
                type(auth),
                "verify_blocked_username",
                raise_blocked,
            )
            blocked_response = client.post(f"{AUTH_URI}/reset", json=request_data)
        assert_neutral(blocked_response)
        assert self._reset_tokens(auth, user) == []

        # Expected SMTP failure is also neutral and leaves no usable token.
        self.delete_mock_email()
        with monkeypatch.context() as patch:
            patch.setattr(
                "nig.endpoints.reset_password.send_password_reset_link",
                lambda *_args, **_kwargs: False,
            )
            smtp_response = client.post(f"{AUTH_URI}/reset", json=request_data)
        assert_neutral(smtp_response)
        assert self._reset_tokens(auth, user) == []

        # An SMTP connector failure before mail delivery is also neutral.
        self.delete_mock_email()
        with monkeypatch.context() as patch:
            patch.setattr(
                "nig.endpoints.reset_password.send_password_reset_link",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    ServiceUnavailable("smtp unavailable")
                ),
            )
            unavailable_response = client.post(
                f"{AUTH_URI}/reset", json=request_data
            )
        assert_neutral(unavailable_response)
        assert self._reset_tokens(auth, user) == []

        # Format validation remains independent from account existence.
        invalid_response = client.post(
            f"{AUTH_URI}/reset", json={"reset_email": "not-an-email"}
        )
        assert invalid_response.status_code == 400

    def test_password_reset_override_structure(self, client: FlaskClient) -> None:
        assert RecoverPassword.post.__module__ == "nig.endpoints.reset_password"
        assert handle_log_output('{"reset_email":"target@example.org"}') == {
            "reset_email": OBSCURE_VALUE
        }

        reset_rules = [
            rule
            for rule in client.application.url_map.iter_rules()
            if rule.rule in {"/auth/reset", "/auth/reset/<token>"}
        ]
        post_rules = [rule for rule in reset_rules if "POST" in rule.methods]
        put_rules = [rule for rule in reset_rules if "PUT" in rule.methods]
        assert len(post_rules) == 1
        assert post_rules[0].rule == "/auth/reset"
        assert len(put_rules) == 1
        assert put_rules[0].rule == "/auth/reset/<token>"

        headers, _ = self.do_login(client, None, None)
        response = client.get(f"{API_URI}/specs", headers=headers)
        assert response.status_code == 200
        specs = self.get_content(response)
        assert isinstance(specs, dict)
        reset_path = specs["paths"]["/auth/reset"]
        token_path = specs["paths"]["/auth/reset/{token}"]
        assert list(method for method in reset_path if method == "post") == ["post"]
        assert list(method for method in token_path if method == "put") == ["put"]
        assert "200" in reset_path["post"]["responses"]
        assert "400" in reset_path["post"]["responses"]
        assert "403" not in reset_path["post"]["responses"]
