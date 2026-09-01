#!/usr/bin/env python3
"""Plan, apply, or roll back the NIG Root/Staff graph migration.

``--dry-run`` never mutates Neo4j. ``--apply`` requires a protected report from
``precheck_admin_hierarchy.py`` and an explicit confirmation string.  No mode reads
or prints passwords, TOTP secrets, JWTs, or token values.
"""

import argparse
import json
import os
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# The runtime image keeps Conda first in PATH for the genomics pipeline, while
# RAPyDo and Neomodel are installed in the system Python site-packages.  This
# operational script must work with either interpreter.
try:
    from neomodel import db as neo4j_db
except ModuleNotFoundError:
    system_site_packages = (
        f"/usr/local/lib/python{sys.version_info.major}."
        f"{sys.version_info.minor}/dist-packages"
    )
    if system_site_packages not in sys.path:
        sys.path.append(system_site_packages)
    from neomodel import db as neo4j_db

from restapi.connectors import Connector
from restapi.env import Env
from restapi.utilities.logs import log

from nig.services.admin_policy import (
    ROOT_ROLE,
    STAFF_ROLE,
    assert_root_integrity,
    roles_for_user,
    snapshot_user,
)
from nig.services.admin_security import audit_admin_action

APPLY_CONFIRMATION = "APPLY_ADMIN_HIERARCHY"
ROLLBACK_CONFIRMATION = "ROLLBACK_ADMIN_HIERARCHY"
REPORT_TYPE = "nig_admin_hierarchy_precheck"


def _default_username() -> str:
    return Env.get("AUTH_DEFAULT_USERNAME", "").lower()


def _state(user: Any, auth: Any) -> Dict[str, Any]:
    state = snapshot_user(user, auth)
    state["is_active"] = getattr(user, "is_active", None)
    expiration = getattr(user, "expiration", None)
    state["expiration"] = expiration.isoformat() if expiration is not None else None
    return state


def _relevant_inventory(auth: Any, default_username: str) -> List[Dict[str, Any]]:
    inventory = []
    for user in auth.get_users():
        roles = roles_for_user(user, auth)
        if (
            ROOT_ROLE in roles
            or STAFF_ROLE in roles
            or str(getattr(user, "email", "")).lower() == default_username
        ):
            inventory.append(
                {
                    "uuid": str(user.uuid),
                    "email": str(user.email),
                    "roles": sorted(roles),
                }
            )
    return sorted(inventory, key=lambda item: item["email"])


def build_plan(auth: Any) -> Dict[str, Any]:
    default_username = _default_username()
    root = auth.get_user(username=default_username)
    changes: List[Dict[str, Any]] = []
    for user in auth.get_users():
        current_roles = roles_for_user(user, auth)
        desired_roles = set(current_roles)
        desired_active = getattr(user, "is_active", None)
        desired_expiration = getattr(user, "expiration", None)
        is_default = str(getattr(user, "email", "")).lower() == default_username

        if is_default:
            desired_roles = {ROOT_ROLE}
            desired_active = True
            desired_expiration = None
        elif ROOT_ROLE in desired_roles:
            desired_roles.remove(ROOT_ROLE)
            desired_roles.add(STAFF_ROLE)

        changed_fields = []
        if desired_roles != current_roles:
            changed_fields.append("roles")
        if desired_active != getattr(user, "is_active", None):
            changed_fields.append("is_active")
        if desired_expiration != getattr(user, "expiration", None):
            changed_fields.append("expiration")
        if changed_fields:
            changes.append(
                {
                    "uuid": str(user.uuid),
                    "email": str(user.email),
                    "before": _state(user, auth),
                    "after": {
                        "roles": sorted(desired_roles),
                        "is_active": desired_active,
                        "expiration": (
                            desired_expiration.isoformat()
                            if desired_expiration is not None
                            else None
                        ),
                    },
                    "changed_fields": changed_fields,
                }
            )

    role_names = {str(role.name) for role in auth.get_roles()}
    errors = []
    if not default_username:
        errors.append("AUTH_DEFAULT_USERNAME is not configured")
    if root is None:
        errors.append("The configured default user does not exist")

    return {
        "report_type": "nig_admin_hierarchy_migration_plan",
        "schema_version": 1,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "default_username": default_username,
        "read_only": True,
        "missing_staff_role_node": STAFF_ROLE not in role_names,
        "changes": changes,
        "errors": errors,
    }


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def _write_private(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def validate_precheck(
    auth: Any,
    report: Dict[str, Any],
    acknowledge_errors: bool,
) -> None:
    if report.get("report_type") != REPORT_TYPE or report.get("read_only") is not True:
        raise ValueError("The supplied file is not a read-only NIG pre-check report")
    if str(report.get("default_username", "")).lower() != _default_username():
        raise ValueError("Pre-check default username does not match this environment")
    if report.get("errors") and not acknowledge_errors:
        raise ValueError(
            "Pre-check reports integrity errors; review them and pass "
            "--acknowledge-precheck-errors only after approval"
        )

    recorded = sorted(
        report.get("original_has_role_inventory", []),
        key=lambda item: item.get("email", ""),
    )
    current = _relevant_inventory(auth, _default_username())
    comparable_recorded = [
        {
            "uuid": str(item.get("uuid", "")),
            "email": str(item.get("email", "")),
            "roles": sorted(set(item.get("roles", []))),
        }
        for item in recorded
    ]
    if comparable_recorded != current:
        raise ValueError(
            "Administrative graph state changed after the pre-check; run it again"
        )


def _revoke_tokens(auth: Any, user: Any) -> int:
    tokens = list(auth.get_tokens(user=user))
    for token in tokens:
        auth.invalidate_token(token=token["token"])
    return len(tokens)


def apply_migration(
    auth: Any,
    precheck: Dict[str, Any],
    rollback_output: Path,
    acknowledge_errors: bool,
) -> Dict[str, Any]:
    touched: List[Any] = []
    revoked_tokens = 0
    neo4j_db.begin()
    try:
        # Revalidate and take the rollback snapshot inside the same transaction as
        # the writes.  This narrows the pre-check/apply race and guarantees that a
        # protected rollback artifact exists before the first graph mutation.
        validate_precheck(auth, precheck, acknowledge_errors)
        plan = build_plan(auth)
        if plan["errors"]:
            raise RuntimeError("; ".join(plan["errors"]))

        role_names = {str(role.name) for role in auth.get_roles()}
        staff_role_created = STAFF_ROLE not in role_names
        rollback_report = {
            "report_type": "nig_admin_hierarchy_rollback",
            "schema_version": 1,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "default_username": _default_username(),
            "staff_role_created": staff_role_created,
            "users": [change["before"] for change in plan["changes"]],
        }
        _write_private(rollback_output, rollback_report)

        if staff_role_created:
            auth.create_role(name=STAFF_ROLE, description="Operational Administrator")

        for change in plan["changes"]:
            user = auth.get_user(user_id=change["uuid"])
            if user is None:
                raise RuntimeError(
                    f"User disappeared during migration: {change['uuid']}"
                )
            if _state(user, auth) != change["before"]:
                raise RuntimeError(
                    f"User changed during migration: {change['uuid']}; run the "
                    "pre-check again"
                )
            auth.link_roles(user, list(change["after"]["roles"]))
            user.is_active = change["after"]["is_active"]
            user.expiration = _parse_datetime(change["after"]["expiration"])
            auth.save_user(user)
            revoked_tokens += _revoke_tokens(auth, user)
            touched.append(user)

        integrity = assert_root_integrity(auth)
        neo4j_db.commit()
    except Exception:
        neo4j_db.rollback()
        raise

    for user, change in zip(touched, plan["changes"]):
        audit_admin_action(
            actor=None,
            target=user,
            action="admin_hierarchy_migration",
            outcome="success",
            reason="approved migration",
            changed_fields=change["changed_fields"],
            before=change["before"],
            after=snapshot_user(user, auth),
        )

    return {
        "report_type": "nig_admin_hierarchy_migration_result",
        "schema_version": 1,
        "completed_at": datetime.utcnow().isoformat() + "Z",
        "changed_users": len(touched),
        "revoked_tokens": revoked_tokens,
        "rollback_report": str(rollback_output),
        "integrity": integrity.as_dict(),
    }


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def rollback_migration(auth: Any, report: Dict[str, Any]) -> Dict[str, Any]:
    if report.get("report_type") != "nig_admin_hierarchy_rollback":
        raise ValueError("The supplied file is not a NIG rollback report")
    if str(report.get("default_username", "")).lower() != _default_username():
        raise ValueError("Rollback report belongs to another environment")

    changed = 0
    revoked = 0
    neo4j_db.begin()
    try:
        for original in report.get("users", []):
            user = auth.get_user(user_id=str(original.get("uuid", "")))
            if user is None:
                raise RuntimeError(
                    "Rollback cannot recreate a deleted user: "
                    + str(original.get("uuid", ""))
                )
            auth.link_roles(user, list(original.get("roles", [])))
            user.is_active = original.get("is_active")
            user.expiration = _parse_datetime(original.get("expiration"))
            auth.save_user(user)
            revoked += _revoke_tokens(auth, user)
            changed += 1

        if report.get("staff_role_created"):
            staff_users = [
                user
                for user in auth.get_users()
                if STAFF_ROLE in roles_for_user(user, auth)
            ]
            if staff_users:
                raise RuntimeError(
                    "Rollback cannot remove staff_user because it is assigned to "
                    "users outside the migration snapshot"
                )
            staff_role = next(
                (
                    role
                    for role in auth.get_roles()
                    if str(getattr(role, "name", "")) == STAFF_ROLE
                ),
                None,
            )
            if staff_role is not None:
                staff_role.delete()
        neo4j_db.commit()
    except Exception:
        neo4j_db.rollback()
        raise

    return {
        "report_type": "nig_admin_hierarchy_rollback_result",
        "completed_at": datetime.utcnow().isoformat() + "Z",
        "restored_users": changed,
        "revoked_tokens": revoked,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--rollback", type=Path)
    parser.add_argument("--precheck-report", type=Path)
    parser.add_argument("--rollback-output", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm")
    parser.add_argument("--acknowledge-precheck-errors", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    auth = Connector.get_authentication_instance()

    if args.dry_run:
        result = build_plan(auth)
    elif args.apply:
        if args.confirm != APPLY_CONFIRMATION:
            raise SystemExit(f"--apply requires --confirm {APPLY_CONFIRMATION}")
        if args.precheck_report is None or args.rollback_output is None:
            raise SystemExit(
                "--apply requires --precheck-report and --rollback-output"
            )
        result = apply_migration(
            auth,
            _load_json(args.precheck_report),
            args.rollback_output,
            args.acknowledge_precheck_errors,
        )
    else:
        if args.confirm != ROLLBACK_CONFIRMATION:
            raise SystemExit(f"--rollback requires --confirm {ROLLBACK_CONFIRMATION}")
        result = rollback_migration(auth, _load_json(args.rollback))

    if args.output:
        _write_private(args.output, result)
        print(f"Protected report written to {args.output}")
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result.get("errors") else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log.error("Admin hierarchy migration failed: {}", type(exc).__name__)
        raise
