from datetime import datetime
from pathlib import Path

import pytz

from nig.scripts import migrate_admin_hierarchy
from nig.scripts.migrate_admin_hierarchy import (
    APPLY_CONFIRMATION,
    ROLLBACK_CONFIRMATION,
    build_plan,
    parse_args as parse_migration_args,
)
from nig.scripts.precheck_admin_hierarchy import (
    FORBIDDEN_CYPHER,
    INVENTORY_QUERY,
    ROLE_QUERY,
    _assert_queries_are_read_only,
    build_report,
)


def test_precheck_queries_and_report_are_read_only() -> None:
    _assert_queries_are_read_only()
    query_text = f"{INVENTORY_QUERY}\n{ROLE_QUERY}".upper()
    for keyword in FORBIDDEN_CYPHER:
        assert f" {keyword} " not in f" {query_text} "

    report = build_report(
        "root@example.org",
        [
            {
                "uuid": "root",
                "email": "root@example.org",
                "is_active": True,
                "expiration": None,
                "roles": ["admin_root"],
            },
            {
                "uuid": "legacy",
                "email": "legacy@example.org",
                "is_active": True,
                "expiration": None,
                "roles": ["admin_root", "normal_user"],
            },
        ],
        [
            {"name": "admin_root", "description": "Admin"},
            {"name": "staff_user", "description": "Admin"},
            {"name": "group_coordinator", "description": "Coordinator"},
            {"name": "normal_user", "description": "User"},
        ],
    )

    assert report["read_only"] is True
    assert report["report_type"] == "nig_admin_hierarchy_precheck"
    assert report["summary"]["root_candidates"] == 2
    assert report["original_has_role_inventory"][1]["roles"] == [
        "admin_root",
        "normal_user",
    ]
    serialized = str(report).lower()
    assert "password" not in serialized
    assert "totp" not in serialized
    assert "token" not in serialized


def test_migration_modes_require_explicit_inputs() -> None:
    dry_run = parse_migration_args(["--dry-run"])
    assert dry_run.dry_run

    apply = parse_migration_args(
        [
            "--apply",
            "--precheck-report",
            "precheck.json",
            "--rollback-output",
            "rollback.json",
            "--confirm",
            APPLY_CONFIRMATION,
        ]
    )
    assert apply.apply
    assert apply.precheck_report == Path("precheck.json")

    rollback = parse_migration_args(
        ["--rollback", "rollback.json", "--confirm", ROLLBACK_CONFIRMATION]
    )
    assert rollback.rollback == Path("rollback.json")


def test_migration_plan_preserves_non_root_expiration(monkeypatch) -> None:
    expiration = datetime(2030, 1, 2, 3, 4, tzinfo=pytz.utc)

    class User:
        uuid = "legacy-admin"
        email = "legacy@example.org"
        name = "Legacy"
        surname = "Admin"
        is_active = True
        belongs_to = None

        def __init__(self) -> None:
            self.expiration = expiration

    class Role:
        def __init__(self, name: str) -> None:
            self.name = name

    class Auth:
        user = User()

        def get_users(self):
            return [self.user]

        def get_user(self, *, username=None, user_id=None):
            return None

        def get_roles_from_user(self, user):
            return ["admin_root"]

        def get_roles(self):
            return [Role("admin_root"), Role("staff_user")]

    monkeypatch.setattr(
        migrate_admin_hierarchy, "_default_username", lambda: "root@example.org"
    )
    plan = build_plan(Auth())

    assert plan["changes"][0]["after"]["roles"] == ["staff_user"]
    assert plan["changes"][0]["after"]["expiration"] == expiration.isoformat()
