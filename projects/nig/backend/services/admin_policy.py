"""Central authorization policy for the NIG administrative hierarchy.

The policy deliberately derives the Root identity from both the configured default
username and the ``admin_root`` relationship.  It never repairs graph state: data
normalization belongs to the explicit migration script.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from restapi.env import Env
from restapi.exceptions import Forbidden
from restapi.services.authentication import BaseAuthentication, Role

ROOT_ROLE = Role.ADMIN.value
STAFF_ROLE = Role.STAFF.value
COORDINATOR_ROLE = Role.COORDINATOR.value
USER_ROLE = Role.USER.value
EXPECTED_ROLE_NODES = {ROOT_ROLE, STAFF_ROLE, COORDINATOR_ROLE, USER_ROLE}
ROOT_ALLOWED_ROLES = {ROOT_ROLE}
STAFF_PEER_FIELDS = {"name", "surname", "group", "email"}
STAFF_SELF_FIELDS = {"name", "surname", "group"}
AUXILIARY_FIELDS = {"email_notification"}
SENSITIVE_FIELDS = {"password", "totp", "totp_code", "token", "access_token"}


class PrincipalKind(str, Enum):
    ROOT = "root"
    STAFF = "staff"
    COORDINATOR = "coordinator"
    USER = "user"
    INVALID_ADMIN = "invalid_admin"


class RootIntegrityError(RuntimeError):
    """Raised when graph state does not contain exactly one valid Root."""


@dataclass(frozen=True)
class RootIntegrityReport:
    default_username: str
    root_uuid: Optional[str]
    root_roles: Sequence[str]
    admin_user_uuids: Sequence[str]
    missing_role_nodes: Sequence[str]
    errors: Sequence[str]

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> Dict[str, Any]:
        return {
            "default_username": self.default_username,
            "root_uuid": self.root_uuid,
            "root_roles": list(self.root_roles),
            "admin_user_uuids": list(self.admin_user_uuids),
            "missing_role_nodes": list(self.missing_role_nodes),
            "errors": list(self.errors),
            "valid": self.valid,
        }


def normalize_roles(roles: Optional[Iterable[Any]]) -> Set[str]:
    """Normalize enum/string/list role payloads into a comparable set."""

    if roles is None:
        return set()
    if isinstance(roles, str):
        value = roles.strip()
        if value.startswith("["):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                parsed = [value]
            roles = parsed
        else:
            roles = [value]

    normalized: Set[str] = set()
    for role in roles:
        if isinstance(role, Role):
            normalized.add(role.value)
        elif isinstance(role, str):
            normalized.add(role)
        elif hasattr(role, "value"):
            normalized.add(str(role.value))
        else:
            normalized.add(str(role))
    return normalized


def roles_for_user(user: Any, auth: Optional[Any] = None) -> Set[str]:
    if auth is not None:
        return normalize_roles(auth.get_roles_from_user(user))
    roles = getattr(user, "roles", None)
    if roles is None:
        return set()
    if hasattr(roles, "all"):
        roles = roles.all()
    return normalize_roles(getattr(role, "name", role) for role in roles)


def configured_root_username() -> str:
    return (
        BaseAuthentication.default_user
        or Env.get("AUTH_DEFAULT_USERNAME", "")
        or ""
    ).lower()


def is_root_identity(
    user: Any,
    auth: Optional[Any] = None,
    default_username: Optional[str] = None,
) -> bool:
    if user is None:
        return False
    expected = (default_username or configured_root_username()).lower()
    email = str(getattr(user, "email", "")).lower()
    return bool(
        expected and email == expected and ROOT_ROLE in roles_for_user(user, auth)
    )


def classify_actor(
    user: Any,
    auth: Optional[Any] = None,
    default_username: Optional[str] = None,
) -> PrincipalKind:
    roles = roles_for_user(user, auth)
    if ROOT_ROLE in roles:
        if is_root_identity(user, auth, default_username):
            return PrincipalKind.ROOT
        return PrincipalKind.INVALID_ADMIN
    if STAFF_ROLE in roles:
        return PrincipalKind.STAFF
    if COORDINATOR_ROLE in roles:
        return PrincipalKind.COORDINATOR
    return PrincipalKind.USER


def classify_target(
    user: Any,
    auth: Optional[Any] = None,
    default_username: Optional[str] = None,
) -> PrincipalKind:
    return classify_actor(user, auth, default_username)


def _group_uuid(user: Any) -> Optional[str]:
    relation = getattr(user, "belongs_to", None)
    if relation is None:
        return None
    group = relation.single() if hasattr(relation, "single") else relation
    return str(getattr(group, "uuid", "")) or None


def snapshot_user(user: Any, auth: Optional[Any] = None) -> Dict[str, Any]:
    expiration = getattr(user, "expiration", None)
    return {
        "uuid": str(getattr(user, "uuid", "")),
        "email": str(getattr(user, "email", "")),
        "name": getattr(user, "name", None),
        "surname": getattr(user, "surname", None),
        "is_active": getattr(user, "is_active", None),
        "expiration": (
            expiration.isoformat() if isinstance(expiration, datetime) else expiration
        ),
        "roles": sorted(roles_for_user(user, auth)),
        "group": _group_uuid(user),
    }


def changed_fields(
    target: Any, changes: Dict[str, Any], auth: Optional[Any] = None
) -> Set[str]:
    """Return semantic changes, ignoring unchanged critical values.

    Password input is necessarily considered a change because only its hash is stored.
    Auxiliary UI fields do not alter account state.
    """

    changed: Set[str] = set()
    current_roles = roles_for_user(target, auth)
    for field, requested in changes.items():
        if field in AUXILIARY_FIELDS:
            continue
        if field in SENSITIVE_FIELDS:
            changed.add(field)
            continue
        if field == "roles":
            if normalize_roles(requested) != current_roles:
                changed.add(field)
            continue
        if field == "group":
            if requested is not None and str(requested) != str(_group_uuid(target)):
                changed.add(field)
            continue
        if field == "email":
            if str(requested).lower() != str(getattr(target, "email", "")).lower():
                changed.add(field)
            continue
        current = getattr(target, field, None)
        if isinstance(current, datetime) and isinstance(requested, datetime):
            if current.replace(tzinfo=None) != requested.replace(tzinfo=None):
                changed.add(field)
        elif current != requested:
            changed.add(field)
    return changed


def validate_create(
    actor: Any,
    requested_roles: Optional[Iterable[Any]],
    properties: Dict[str, Any],
    auth: Optional[Any] = None,
) -> Set[str]:
    del properties  # reserved for future custom-field policy decisions
    actor_kind = classify_actor(actor, auth)
    if actor_kind not in {PrincipalKind.ROOT, PrincipalKind.STAFF}:
        raise Forbidden("Administrative user creation is not allowed")

    roles = normalize_roles(requested_roles)
    if ROOT_ROLE in roles:
        raise Forbidden("The Root role cannot be assigned through the users API")
    unknown = roles - EXPECTED_ROLE_NODES
    if unknown:
        raise Forbidden("One or more requested roles are not allowed")
    return roles


def validate_update(
    actor: Any,
    target: Any,
    changes: Dict[str, Any],
    auth: Optional[Any] = None,
) -> Set[str]:
    actor_kind = classify_actor(actor, auth)
    target_kind = classify_target(target, auth)
    semantic_changes = changed_fields(target, changes, auth)

    if actor_kind not in {PrincipalKind.ROOT, PrincipalKind.STAFF}:
        raise Forbidden("Administrative user modification is not allowed")
    if target_kind == PrincipalKind.ROOT:
        raise Forbidden("The Root account is immutable through the users API")
    if target_kind == PrincipalKind.INVALID_ADMIN:
        raise Forbidden("Invalid administrative state requires the migration procedure")

    effective_roles = normalize_roles(changes.get("roles", roles_for_user(target, auth)))
    if ROOT_ROLE in effective_roles:
        raise Forbidden("The Root role cannot be assigned through the users API")
    if effective_roles - EXPECTED_ROLE_NODES:
        raise Forbidden("One or more requested roles are not allowed")

    if actor_kind == PrincipalKind.STAFF:
        if target_kind == PrincipalKind.STAFF:
            self_target = str(getattr(actor, "uuid", "")) == str(
                getattr(target, "uuid", "")
            )
            allowed = STAFF_SELF_FIELDS if self_target else STAFF_PEER_FIELDS
            forbidden_changes = semantic_changes - allowed
            if forbidden_changes:
                raise Forbidden(
                    "Staff accounts can only receive non-critical peer updates"
                )
        elif STAFF_ROLE in effective_roles:
            # Staff may create another Staff, but promotion/revocation is Root-only.
            raise Forbidden("Only Root can promote an existing account to Staff")

    return semantic_changes


def validate_delete(actor: Any, target: Any, auth: Optional[Any] = None) -> None:
    actor_kind = classify_actor(actor, auth)
    target_kind = classify_target(target, auth)
    if actor_kind not in {PrincipalKind.ROOT, PrincipalKind.STAFF}:
        raise Forbidden("Administrative user deletion is not allowed")
    if target_kind == PrincipalKind.ROOT:
        raise Forbidden("The Root account cannot be deleted through the users API")
    if target_kind == PrincipalKind.INVALID_ADMIN:
        raise Forbidden("Invalid administrative state requires the migration procedure")
    if actor_kind == PrincipalKind.STAFF and target_kind == PrincipalKind.STAFF:
        raise Forbidden("Staff accounts cannot delete Staff peers or themselves")


def inspect_root_integrity(auth: Any) -> RootIntegrityReport:
    default_username = configured_root_username()
    users: List[Any] = list(auth.get_users())
    role_nodes = {str(role.name) for role in auth.get_roles()}
    default_user = next(
        (
            user
            for user in users
            if str(getattr(user, "email", "")).lower() == default_username
        ),
        None,
    )
    admin_users = [user for user in users if ROOT_ROLE in roles_for_user(user, auth)]
    errors: List[str] = []

    if not default_username:
        errors.append("AUTH_DEFAULT_USERNAME is not configured")
    if default_user is None:
        errors.append("The configured default user does not exist")
    if default_user is not None and ROOT_ROLE not in roles_for_user(
        default_user, auth
    ):
        errors.append("The configured default user does not have admin_root")
    if len(admin_users) != 1:
        errors.append("Exactly one user must have admin_root")
    elif default_user is not None and admin_users[0].uuid != default_user.uuid:
        errors.append(
            "admin_root belongs to a user other than the configured default user"
        )

    root_roles = sorted(roles_for_user(default_user, auth)) if default_user else []
    if default_user is not None:
        if getattr(default_user, "is_active", None) is not True:
            errors.append("The Root account is inactive")
        if getattr(default_user, "expiration", None) is not None:
            errors.append("The Root account has an expiration")
        if set(root_roles) != ROOT_ALLOWED_ROLES:
            errors.append("The Root account must have only admin_root")

    missing_roles = sorted(EXPECTED_ROLE_NODES - role_nodes)
    if missing_roles:
        errors.append("One or more required role nodes are missing")
    if (
        Env.get_bool("AUTH_ROOT_TOTP_REQUIRED", True)
        and not BaseAuthentication.SECOND_FACTOR_AUTHENTICATION
    ):
        errors.append("Global TOTP authentication is disabled")

    return RootIntegrityReport(
        default_username=default_username,
        root_uuid=str(getattr(default_user, "uuid", "")) or None,
        root_roles=root_roles,
        admin_user_uuids=sorted(str(user.uuid) for user in admin_users),
        missing_role_nodes=missing_roles,
        errors=errors,
    )


def assert_root_integrity(auth: Any) -> RootIntegrityReport:
    report = inspect_root_integrity(auth)
    if not report.valid:
        raise RootIntegrityError("; ".join(report.errors))
    return report
