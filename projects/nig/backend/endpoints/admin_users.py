"""Project-only policy guards for the inherited RAPyDo admin-user endpoints.

This module replaces methods on the already loaded framework class.  It does not
register another EndpointResource, so Flask and OpenAPI retain one operation for
each method/path pair.
"""

import inspect
from typing import Any, Dict, List, Set, Type

from flask import request
from restapi import decorators
from restapi.config import PRODUCTION
from restapi.customizer import FlaskRequest
from restapi.endpoints.admin_users import AdminUsers
from restapi.endpoints.admin_users import inject_user as core_inject_user
from restapi.endpoints.schemas import (
    admin_user_post_input as core_admin_user_post_input,
    admin_user_put_input as core_admin_user_put_input,
)
from restapi.env import Env
from restapi.exceptions import Forbidden, NotFound, ServiceUnavailable
from restapi.models import Schema, fields, validate
from restapi.rest.definition import EndpointResource, Response
from restapi.services.authentication import Role, User
from restapi.utilities.logs import log

from nig.services.admin_policy import (
    RootIntegrityError,
    assert_root_integrity,
    roles_for_user,
    snapshot_user,
    validate_create,
    validate_delete,
    validate_update,
)
from nig.services.admin_security import (
    audit_admin_action,
    notify_admin_action,
    notify_denied_admin_action,
)

_CORE_POST = inspect.unwrap(AdminUsers.post)
_CORE_PUT = inspect.unwrap(AdminUsers.put)
_CORE_DELETE = inspect.unwrap(AdminUsers.delete)
NOT_FOUND_MESSAGE = "This user cannot be found or you are not authorized"


def _assignable_roles_field() -> Any:
    """Return a roles field that never exposes the immutable Root role."""

    roles = [
        (Role.STAFF.value, "Operational Administrator"),
        (Role.COORDINATOR.value, "Group Coordinator"),
        (Role.USER.value, "Normal User"),
    ]
    return fields.List(
        fields.Str(
            validate=validate.OneOf(
                choices=[role for role, _ in roles],
                labels=[label for _, label in roles],
            )
        ),
        dump_default=[Role.USER.value],
        required=False,
        unique=True,
        metadata={"label": "Roles", "description": ""},
    )


def admin_user_post_input(request: FlaskRequest) -> Type[Schema]:
    """Hide ``admin_root`` from every administrative creation form."""

    base_schema = core_admin_user_post_input(request)

    class NIGAdminUserCreate(base_schema):  # type: ignore
        roles = _assignable_roles_field()

    return NIGAdminUserCreate


def admin_user_put_input(request: FlaskRequest) -> Type[Schema]:
    """Extend the PUT schema while hiding the immutable Root role."""

    base_schema = core_admin_user_put_input(request)

    class NIGAdminUserUpdate(base_schema):  # type: ignore
        email = fields.Email(required=False, validate=validate.Length(max=100))
        roles = _assignable_roles_field()

    return NIGAdminUserUpdate


def _enforce_integrity(endpoint: EndpointResource) -> None:
    """Fail closed in production while permitting explicit local migration work."""

    if not PRODUCTION and not Env.get_bool("AUTH_ADMIN_HIERARCHY_ENFORCE"):
        return
    try:
        assert_root_integrity(endpoint.auth)
    except RootIntegrityError as exc:
        log.critical("Root integrity check failed: {}", exc)
        raise ServiceUnavailable(
            "Administrative API unavailable: Root integrity failure"
        )


def inject_user(
    endpoint: EndpointResource, user_id: str, user: User
) -> Dict[str, Any]:
    """Preserve the core 404 contract while auditing Staff attempts on Root."""

    target = endpoint.auth.get_user(user_id=user_id)
    if target is None:
        raise NotFound(NOT_FOUND_MESSAGE)
    if endpoint.auth.is_admin(target) and not endpoint.auth.is_admin(user):
        reason = "Staff attempted to target the Root account"
        audit_admin_action(
            actor=user,
            target=target,
            action=f"admin_user_{request.method.lower()}",
            outcome="denied",
            reason=reason,
        )
        notify_denied_admin_action(
            auth=endpoint.auth,
            actor=user,
            target=target,
            action="admin_user_root_access",
            reason=reason,
        )
        raise NotFound(NOT_FOUND_MESSAGE)
    # Keep any additional core preload behavior if RAPyDo adds it in this release.
    return core_inject_user(endpoint, user_id, user)


def _revoke_tokens(auth: Any, target: Any) -> None:
    for token in list(auth.get_tokens(user=target)):
        auth.invalidate_token(token=token["token"])


def _denied(
    endpoint: EndpointResource,
    actor: Any,
    target: Any,
    action: str,
    exc: Forbidden,
    changed: Set[str],
) -> None:
    reason = str(exc)
    audit_admin_action(
        actor=actor,
        target=target,
        action=action,
        outcome="denied",
        reason=reason,
        changed_fields=changed,
    )
    notify_denied_admin_action(
        auth=endpoint.auth,
        actor=actor,
        target=target,
        action=action,
        reason=reason,
    )


@decorators.auth.require_any(Role.ADMIN, Role.STAFF)
@decorators.database_transaction
@decorators.use_kwargs(admin_user_post_input)
@decorators.endpoint(
    path="/admin/users",
    summary="Create a new user under the NIG administrative hierarchy",
    responses={
        200: "The uuid of the new user is returned",
        403: "The requested role assignment is forbidden",
        409: "This user already exists",
        503: "Root integrity check failed",
    },
)
def post(self: Any, user: User, **kwargs: Any) -> Response:
    _enforce_integrity(self)
    requested_roles: List[str] = kwargs.get("roles", [])
    try:
        validate_create(user, requested_roles, kwargs, self.auth)
    except Forbidden as exc:
        _denied(self, user, None, "admin_user_create", exc, set(kwargs))
        raise

    try:
        response = _CORE_POST(self, user=user, **kwargs)
        target = self.auth.get_user(username=str(kwargs["email"]).lower())
        after = snapshot_user(target, self.auth) if target is not None else {}
        audit_admin_action(
            actor=user,
            target=target,
            action="admin_user_create",
            outcome="success",
            reason="authorized",
            changed_fields=set(kwargs) - {"password"},
            after=after,
        )
        if target is not None and Role.STAFF.value in after.get("roles", []):
            notify_admin_action(
                auth=self.auth,
                actor=user,
                target=target,
                action="admin_user_create",
                changed_fields={"roles"},
                after=after,
            )
        return response
    except Exception as exc:
        audit_admin_action(
            actor=user,
            target=None,
            action="admin_user_create",
            outcome="error",
            reason=type(exc).__name__,
            changed_fields=set(kwargs) - {"password"},
        )
        raise


@decorators.auth.require_any(Role.ADMIN, Role.STAFF)
@decorators.preload(callback=inject_user)
@decorators.database_transaction
@decorators.use_kwargs(admin_user_put_input)
@decorators.endpoint(
    path="/admin/users/<user_id>",
    summary="Modify a user under the NIG administrative hierarchy",
    responses={
        200: "User successfully modified",
        403: "The requested modification is forbidden",
        503: "Root integrity check failed",
    },
)
def put(
    self: Any, user_id: str, target_user: User, user: User, **kwargs: Any
) -> Response:
    _enforce_integrity(self)
    original_changes = dict(kwargs)
    before = snapshot_user(target_user, self.auth)
    try:
        changed = validate_update(user, target_user, original_changes, self.auth)
    except Forbidden as exc:
        _denied(
            self,
            user,
            target_user,
            "admin_user_update",
            exc,
            set(original_changes),
        )
        raise

    # RAPyDo treats an omitted roles field as the default role.  Preserve current
    # roles for partial updates so an innocent name change cannot demote a user.
    kwargs.setdefault("roles", sorted(roles_for_user(target_user, self.auth)))

    try:
        response = _CORE_PUT(
            self,
            user_id=user_id,
            target_user=target_user,
            user=user,
            **kwargs,
        )
        after = snapshot_user(target_user, self.auth)
        if before["roles"] != after["roles"]:
            _revoke_tokens(self.auth, target_user)
        audit_admin_action(
            actor=user,
            target=target_user,
            action="admin_user_update",
            outcome="success",
            reason="authorized",
            changed_fields=changed,
            before=before,
            after=after,
        )
        if changed:
            notify_admin_action(
                auth=self.auth,
                actor=user,
                target=target_user,
                action="admin_user_update",
                changed_fields=changed,
                before=before,
                after=after,
            )
        return response
    except Exception as exc:
        audit_admin_action(
            actor=user,
            target=target_user,
            action="admin_user_update",
            outcome="error",
            reason=type(exc).__name__,
            changed_fields=set(original_changes),
            before=before,
        )
        raise


@decorators.auth.require_any(Role.ADMIN, Role.STAFF)
@decorators.preload(callback=inject_user)
@decorators.endpoint(
    path="/admin/users/<user_id>",
    summary="Delete a user under the NIG administrative hierarchy",
    responses={
        200: "User successfully deleted",
        403: "The requested deletion is forbidden",
        503: "Root integrity check failed",
    },
)
def delete(self: Any, user_id: str, target_user: User, user: User) -> Response:
    _enforce_integrity(self)
    before = snapshot_user(target_user, self.auth)
    try:
        validate_delete(user, target_user, self.auth)
    except Forbidden as exc:
        _denied(self, user, target_user, "admin_user_delete", exc, set())
        raise

    try:
        response = _CORE_DELETE(
            self, user_id=user_id, target_user=target_user, user=user
        )
        audit_admin_action(
            actor=user,
            target=target_user,
            action="admin_user_delete",
            outcome="success",
            reason="authorized",
            before=before,
        )
        notify_admin_action(
            auth=self.auth,
            actor=user,
            target=target_user,
            action="admin_user_delete",
            changed_fields={"deleted"},
            before=before,
            after={},
        )
        return response
    except Exception as exc:
        audit_admin_action(
            actor=user,
            target=target_user,
            action="admin_user_delete",
            outcome="error",
            reason=type(exc).__name__,
            before=before,
        )
        raise


# Core endpoints were already wrapped during the framework loader pass.  Apply the
# central exception adapter to the replacement methods before Flask calls as_view().
setattr(AdminUsers, "post", decorators.catch_exceptions()(post))
setattr(AdminUsers, "put", decorators.catch_exceptions()(put))
setattr(AdminUsers, "delete", decorators.catch_exceptions()(delete))
