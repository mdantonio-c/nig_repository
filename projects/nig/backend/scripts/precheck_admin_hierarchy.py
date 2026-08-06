#!/usr/bin/env python3
"""Read-only production inventory for the NIG administrative hierarchy.

Use only a Neo4j account whose privileges are limited to MATCH on User/Role and
HAS_ROLE.  The script fixes its own Cypher statements and opens a READ session; it
contains no graph mutation statement.
"""

import argparse
import getpass
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from neo4j import GraphDatabase, READ_ACCESS

EXPECTED_ROLES = {
    "admin_root",
    "staff_user",
    "group_coordinator",
    "normal_user",
}
INVENTORY_QUERY = """
MATCH (u:User)
OPTIONAL MATCH (u)-[:HAS_ROLE]->(r:Role)
WITH u, collect(r.name) AS roles
WHERE 'admin_root' IN roles
   OR 'staff_user' IN roles
   OR u.email = $default_username
RETURN u.uuid AS uuid, u.email AS email, u.is_active AS is_active,
       u.expiration AS expiration, roles
ORDER BY email
"""
ROLE_QUERY = """
MATCH (r:Role)
RETURN r.name AS name, r.description AS description
ORDER BY name
"""
FORBIDDEN_CYPHER = {"CREATE", "MERGE", "SET", "DELETE", "DETACH", "REMOVE", "DROP"}


def _assert_queries_are_read_only() -> None:
    for query in (INVENTORY_QUERY, ROLE_QUERY):
        tokens = {token.strip("(),.:;`[]{}'\"").upper() for token in query.split()}
        forbidden = tokens.intersection(FORBIDDEN_CYPHER)
        if forbidden:
            raise RuntimeError(
                "Pre-check contains a forbidden Cypher keyword: "
                + ", ".join(sorted(forbidden))
            )


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def build_report(
    default_username: str,
    inventory: Sequence[Dict[str, Any]],
    role_nodes: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    normalized_default = default_username.lower()
    users: List[Dict[str, Any]] = []
    for entry in inventory:
        user = dict(entry)
        user["roles"] = sorted(set(user.get("roles") or []))
        users.append(_serialize(user))

    root_candidates = [user for user in users if "admin_root" in user["roles"]]
    default_users = [
        user for user in users if str(user.get("email", "")).lower() == normalized_default
    ]
    staff_users = [user for user in users if "staff_user" in user["roles"]]
    inactive_or_expired = [
        user
        for user in users
        if user.get("is_active") is not True or user.get("expiration") is not None
    ]
    incompatible = []
    for user in users:
        roles = set(user["roles"])
        is_default = str(user.get("email", "")).lower() == normalized_default
        if is_default and roles != {"admin_root"}:
            incompatible.append(
                {
                    "uuid": user.get("uuid"),
                    "email": user.get("email"),
                    "roles": user["roles"],
                }
            )
        elif not is_default and "admin_root" in roles:
            incompatible.append(
                {
                    "uuid": user.get("uuid"),
                    "email": user.get("email"),
                    "roles": user["roles"],
                }
            )

    role_names = {str(role.get("name")) for role in role_nodes}
    losing_operational_role = []
    for user in root_candidates:
        roles_after = set(user["roles"])
        if str(user.get("email", "")).lower() == normalized_default:
            roles_after = {"admin_root"}
        else:
            roles_after.discard("admin_root")
            roles_after.add("staff_user")
        if not roles_after.intersection(EXPECTED_ROLES):
            losing_operational_role.append(user)

    errors: List[str] = []
    if len(default_users) != 1:
        errors.append(
            "Expected exactly one user matching the configured default username"
        )
    if len(root_candidates) != 1:
        errors.append("Expected exactly one user with admin_root")
    if default_users and "admin_root" not in default_users[0]["roles"]:
        errors.append("The configured default user does not have admin_root")

    return {
        "report_type": "nig_admin_hierarchy_precheck",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "default_username": normalized_default,
        "summary": {
            "root_candidates": len(root_candidates),
            "staff_users": len(staff_users),
            "inactive_or_expired_admin_users": len(inactive_or_expired),
            "incompatible_role_combinations": len(incompatible),
        },
        "default_user": default_users[0] if len(default_users) == 1 else None,
        "root_candidates": root_candidates,
        "staff_users": staff_users,
        "inactive_or_expired_admin_users": inactive_or_expired,
        "incompatible_role_combinations": incompatible,
        "role_nodes": [_serialize(dict(role)) for role in role_nodes],
        "missing_role_nodes": sorted(EXPECTED_ROLES - role_names),
        "users_losing_every_operational_role": losing_operational_role,
        "original_has_role_inventory": [
            {
                "uuid": user.get("uuid"),
                "email": user.get("email"),
                "roles": user["roles"],
            }
            for user in users
        ],
        "errors": errors,
    }


def _write_private_report(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(str(path), flags, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def run_precheck(
    *,
    uri: str,
    username: str,
    password: str,
    database: str,
    default_username: str,
) -> Dict[str, Any]:
    _assert_queries_are_read_only()
    if "@" in uri:
        raise ValueError("Do not embed credentials in the Neo4j URI")

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(
            database=database, default_access_mode=READ_ACCESS
        ) as session:
            inventory = session.read_transaction(
                lambda tx: [
                    dict(record)
                    for record in tx.run(
                        INVENTORY_QUERY,
                        default_username=default_username.lower(),
                    )
                ]
            )
            role_nodes = session.read_transaction(
                lambda tx: [dict(record) for record in tx.run(ROLE_QUERY)]
            )
    finally:
        driver.close()
    return build_report(default_username, inventory, role_nodes)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", required=True, help="Bolt URI without credentials")
    parser.add_argument("--username", required=True, help="Dedicated read-only username")
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--default-username", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    password = os.environ.get("NIG_NEO4J_PRECHECK_PASSWORD")
    if password is None:
        password = getpass.getpass("Neo4j read-only password: ")
    report = run_precheck(
        uri=args.uri,
        username=args.username,
        password=password,
        database=args.database,
        default_username=args.default_username,
    )
    _write_private_report(args.output, report)
    print(
        "Read-only pre-check completed. Protected report written to "
        f"{args.output}. Errors: {len(report['errors'])}."
    )
    return 2 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
