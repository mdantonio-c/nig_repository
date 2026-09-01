from datetime import datetime
from pathlib import Path

import pytz

from nig.scripts import migrate_admin_hierarchy
from nig.scripts.migrate_admin_hierarchy import (
    APPLY_CONFIRMATION,
    ROLLBACK_CONFIRMATION,
    apply_migration,
    build_plan,
    parse_args as parse_migration_args,
    rollback_migration,
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


def test_rollback_removes_staff_role_created_by_migration(monkeypatch) -> None:
    class User:
        uuid = "legacy-admin"
        email = "legacy@example.org"
        is_active = True
        expiration = None

    class Role:
        name = "staff_user"
        deleted = False

        def delete(self) -> None:
            self.deleted = True

    class Auth:
        user = User()
        role = Role()

        def get_user(self, *, user_id=None, username=None):
            return self.user if user_id == self.user.uuid else None

        def get_users(self):
            return [self.user]

        def get_roles_from_user(self, user):
            return ["admin_root"]

        def get_roles(self):
            return [self.role]

        def link_roles(self, user, roles):
            assert roles == ["admin_root"]

        def save_user(self, user):
            return True

        def get_tokens(self, user):
            return []

    class Transaction:
        def begin(self):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(migrate_admin_hierarchy, "neo4j_db", Transaction())
    monkeypatch.setattr(
        migrate_admin_hierarchy, "_default_username", lambda: "root@example.org"
    )

    result = rollback_migration(
        Auth(),
        {
            "report_type": "nig_admin_hierarchy_rollback",
            "default_username": "root@example.org",
            "staff_role_created": True,
            "users": [
                {
                    "uuid": "legacy-admin",
                    "roles": ["admin_root"],
                    "is_active": True,
                    "expiration": None,
                }
            ],
        },
    )

    assert result["restored_users"] == 1
    assert Auth.role.deleted is True


def test_apply_records_when_it_creates_staff_role(monkeypatch, tmp_path) -> None:
    class Role:
        name = "admin_root"

    class Auth:
        created_role = None

        def get_roles(self):
            return [Role()]

        def create_role(self, name, description):
            self.created_role = (name, description)

    class Transaction:
        def begin(self):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

    class Integrity:
        def as_dict(self):
            return {"valid": True}

    monkeypatch.setattr(migrate_admin_hierarchy, "neo4j_db", Transaction())
    monkeypatch.setattr(migrate_admin_hierarchy, "validate_precheck", lambda *args: None)
    monkeypatch.setattr(
        migrate_admin_hierarchy,
        "build_plan",
        lambda auth: {"errors": [], "changes": []},
    )
    monkeypatch.setattr(
        migrate_admin_hierarchy, "assert_root_integrity", lambda auth: Integrity()
    )

    auth = Auth()
    rollback = tmp_path / "rollback.json"
    result = apply_migration(auth, {}, rollback, acknowledge_errors=False)

    assert auth.created_role == ("staff_user", "Operational Administrator")
    assert result["changed_users"] == 0
    assert migrate_admin_hierarchy._load_json(rollback)["staff_role_created"] is True
