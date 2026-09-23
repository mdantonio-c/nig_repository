from datetime import datetime, timedelta
from typing import Any, Iterable, List, Optional

import pytest
import pytz
from nig.services.admin_policy import (
    PrincipalKind,
    RootIntegrityError,
    assert_root_integrity,
    classify_actor,
    is_root_identity,
    validate_create,
    validate_delete,
    validate_update,
)
from restapi.exceptions import Forbidden
from restapi.services.authentication import BaseAuthentication


class FakeRole:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeRoles:
    def __init__(self, roles: Iterable[str]) -> None:
        self.values = [FakeRole(role) for role in roles]

    def all(self) -> List[FakeRole]:
        return self.values


class FakeGroup:
    uuid = "group-1"


class FakeGroupRelation:
    def single(self) -> FakeGroup:
        return FakeGroup()


class FakeUser:
    def __init__(
        self,
        uuid: str,
        email: str,
        roles: Iterable[str],
        *,
        is_active: bool = True,
        expiration: Optional[datetime] = None,
    ) -> None:
        self.uuid = uuid
        self.email = email
        self.name = "Name"
        self.surname = "Surname"
        self.roles = FakeRoles(roles)
        self.belongs_to = FakeGroupRelation()
        self.is_active = is_active
        self.expiration = expiration


class FakeAuth:
    def __init__(self, users: Iterable[FakeUser]) -> None:
        self.users = list(users)
        self.role_nodes = [
            FakeRole("admin_root"),
            FakeRole("staff_user"),
            FakeRole("group_coordinator"),
            FakeRole("normal_user"),
        ]

    def get_users(self) -> List[FakeUser]:
        return self.users

    def get_roles(self) -> List[FakeRole]:
        return self.role_nodes

    def get_roles_from_user(self, user: FakeUser) -> List[str]:
        return [role.name for role in user.roles.all()]


def test_root_identity_is_hybrid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BaseAuthentication, "default_user", "root@example.org")
    root = FakeUser("root", "root@example.org", ["admin_root"])
    wrong_email = FakeUser("other", "other@example.org", ["admin_root"])
    missing_role = FakeUser("missing", "root@example.org", ["normal_user"])

    assert is_root_identity(root)
    assert not is_root_identity(wrong_email)
    assert not is_root_identity(missing_role)
    assert classify_actor(wrong_email) == PrincipalKind.INVALID_ADMIN


def test_staff_peer_and_self_update_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BaseAuthentication, "default_user", "root@example.org")
    staff = FakeUser("staff-1", "staff1@example.org", ["staff_user"])
    peer = FakeUser("staff-2", "staff2@example.org", ["staff_user"])

    assert validate_update(staff, peer, {"name": "New name"}) == {"name"}
    assert validate_update(staff, peer, {"email": "new@example.org"}) == {"email"}
    assert validate_update(
        staff,
        peer,
        {
            "roles": ["staff_user"],
            "is_active": True,
            "expiration": None,
        },
    ) == set()

    for change in (
        {"is_active": False},
        {"roles": ["normal_user"]},
        {"password": "not-logged"},
        {"expiration": datetime.now(pytz.utc) + timedelta(days=1)},
    ):
        with pytest.raises(Forbidden):
            validate_update(staff, peer, change)

    with pytest.raises(Forbidden):
        validate_update(staff, staff, {"email": "self-new@example.org"})
    assert validate_update(staff, staff, {"group": "group-2"}) == {"group"}


def test_staff_can_manage_users_but_not_promote_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(BaseAuthentication, "default_user", "root@example.org")
    staff = FakeUser("staff", "staff@example.org", ["staff_user"])
    normal = FakeUser("user", "user@example.org", ["normal_user"])

    assert validate_update(staff, normal, {"is_active": False}) == {"is_active"}
    validate_delete(staff, normal)
    with pytest.raises(Forbidden):
        validate_update(staff, normal, {"roles": ["staff_user"]})
    assert validate_create(staff, ["staff_user"], {}) == {"staff_user"}
    with pytest.raises(Forbidden):
        validate_create(staff, ["admin_root"], {})


def test_root_is_immutable_but_can_manage_staff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(BaseAuthentication, "default_user", "root@example.org")
    root = FakeUser("root", "root@example.org", ["admin_root"])
    staff = FakeUser("staff", "staff@example.org", ["staff_user"])

    with pytest.raises(Forbidden):
        validate_update(root, root, {"name": "Changed"})
    with pytest.raises(Forbidden):
        validate_delete(root, root)
    assert validate_update(root, staff, {"roles": ["normal_user"]}) == {"roles"}
    validate_delete(root, staff)


def test_root_integrity_detects_second_admin_and_invalid_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(BaseAuthentication, "default_user", "root@example.org")
    monkeypatch.setattr(BaseAuthentication, "SECOND_FACTOR_AUTHENTICATION", True)
    root = FakeUser("root", "root@example.org", ["admin_root"])
    auth = FakeAuth([root])

    assert assert_root_integrity(auth).valid

    root.roles = FakeRoles(["admin_root", "staff_user"])
    with pytest.raises(RootIntegrityError):
        assert_root_integrity(auth)

    root.roles = FakeRoles(["admin_root"])
    auth.users.append(FakeUser("other", "other@example.org", ["admin_root"]))
    with pytest.raises(RootIntegrityError):
        assert_root_integrity(auth)

    auth.users = [root]
    root.is_active = False
    root.expiration = datetime.now(pytz.utc)
    with pytest.raises(RootIntegrityError):
        assert_root_integrity(auth)


def test_root_integrity_allows_dev_totp_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(BaseAuthentication, "default_user", "root@example.org")
    monkeypatch.setattr(BaseAuthentication, "SECOND_FACTOR_AUTHENTICATION", False)
    monkeypatch.setattr(
        "nig.services.admin_policy.Env.get_bool",
        lambda name, default=False: False
        if name == "AUTH_ROOT_TOTP_REQUIRED"
        else default,
    )
    root = FakeUser("root", "root@example.org", ["admin_root"])

    auth = FakeAuth([root])
    assert assert_root_integrity(auth).valid
    assert validate_create(root, ["staff_user", "normal_user"], {}, auth) == {
        "staff_user",
        "normal_user",
    }


def test_root_integrity_requires_totp_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(BaseAuthentication, "default_user", "root@example.org")
    monkeypatch.setattr(BaseAuthentication, "SECOND_FACTOR_AUTHENTICATION", False)
    root = FakeUser("root", "root@example.org", ["admin_root"])

    with pytest.raises(RootIntegrityError, match="Global TOTP authentication"):
        assert_root_integrity(FakeAuth([root]))
