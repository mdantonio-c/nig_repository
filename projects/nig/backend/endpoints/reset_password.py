from typing import Any

from restapi import decorators
from restapi.config import get_frontend_url
from restapi.connectors import Connector
from restapi.connectors.smtp.notifications import send_password_reset_link
from restapi.env import Env
from restapi.exceptions import Forbidden, ServiceUnavailable
from restapi.models import fields
from restapi.rest.definition import Response
from restapi.utilities.logs import OBSCURED_FIELDS, log

RESET_RESPONSE = (
    "We'll send instructions to the email provided if it's associated with an "
    "account. Please check your spam/junk folder."
)

if "reset_email" not in OBSCURED_FIELDS:
    OBSCURED_FIELDS.append("reset_email")


# The framework defines RecoverPassword only when SMTP is available. Patch the same
# class object after the core loader pass and before Flask creates its MethodView.
if Connector.check_availability("smtp"):
    from restapi.endpoints.reset_password import RecoverPassword

    @decorators.use_kwargs({"reset_email": fields.Email(required=True)})
    @decorators.endpoint(
        path="/auth/reset",
        summary="Request password reset via email",
        description="Request password reset via email",
        responses={
            200: "Password reset request accepted",
            400: "Invalid reset email",
        },
    )
    def post(self: Any, reset_email: str) -> Response:
        reset_email = reset_email.lower()
        user = self.auth.get_user(username=reset_email)

        if user is None:
            log.warning("Password reset request ignored: account not found")
            return self.response(RESET_RESPONSE)

        try:
            self.auth.verify_blocked_username(reset_email)
            self.auth.verify_user_status(user)
        except Forbidden:
            log.warning("Password reset request ignored: account not eligible")
            return self.response(RESET_RESPONSE)

        reset_token, payload = self.auth.create_temporary_token(
            user, self.auth.PWD_RESET
        )
        reset_token_uri = reset_token.replace(".", "+")
        reset_uri = Env.get("RESET_PASSWORD_URI", "/public/reset")
        complete_uri = f"{get_frontend_url()}{reset_uri}/{reset_token_uri}"

        try:
            sent = send_password_reset_link(user, complete_uri, reset_email)
        except ServiceUnavailable:
            sent = False

        if not sent:
            log.error("Password reset email delivery failed")
            return self.response(RESET_RESPONSE)

        self.auth.save_token(
            user, reset_token, payload, token_type=self.auth.PWD_RESET
        )
        self.log_event(self.events.reset_password_request, user=user)
        return self.response(RESET_RESPONSE)

    # RAPyDo has already wrapped core endpoints before importing custom modules.
    # Apply the wrapper explicitly, then replace only POST on the retained class.
    setattr(RecoverPassword, "post", decorators.catch_exceptions()(post))
