import shutil
from typing import Any, Dict, List, Optional, Tuple

import pytest
from faker import Faker
from nig.endpoints import INPUT_ROOT, OUTPUT_ROOT
from restapi.config import DATA_PATH
from restapi.services.authentication import Role
from restapi.tests import API_URI, BaseTests, FlaskClient
from restapi.utilities.logs import log

# Pipeline working directories (one per Celery task uuid)
JOBS_ROOT = DATA_PATH.joinpath("jobs")


class TestEnv:
    """Track and tear down every resource owned by a single test.

    A test creates groups, users and studies (with their datasets/files/jobs)
    through this helper. Teardown is registered on a pytest ``yield`` fixture so
    it always runs, including after an assertion failure. Cleanup is idempotent
    and best-effort: resources already removed by the test body are tolerated,
    every removal is attempted even if a previous one fails, and problems are
    reported only once all attempts are done.
    """

    # Not a pytest test class despite the "Test" prefix
    __test__ = False

    def __init__(self, client: FlaskClient, faker: Faker) -> None:
        self.client = client
        self.faker = faker
        self.admin_headers, _ = BaseTests.do_login(client, None, None)
        # Test-owned resources, tracked for teardown
        self.group_uuids: List[str] = []
        self.user_uuids: List[str] = []
        # study uuid -> owner headers (owner deletion triggers filesystem cleanup)
        self.studies: Dict[str, Optional[Dict[str, str]]] = {}
        self.job_uuids: List[str] = []

    # ------------------------------------------------------------------ #
    # creation helpers
    # ------------------------------------------------------------------ #
    def create_group(self) -> str:
        uuid, _ = BaseTests.create_group(self.client)
        self.group_uuids.append(uuid)
        return uuid

    def create_user(
        self, group_uuid: str
    ) -> Tuple[str, Optional[Dict[str, str]]]:
        uuid, data = BaseTests.create_user(
            self.client, data={"group": group_uuid}, roles=[Role.USER]
        )
        self.user_uuids.append(uuid)
        headers, _ = BaseTests.do_login(
            self.client, data.get("email"), data.get("password")
        )
        return uuid, headers

    def create_study(self, headers: Optional[Dict[str, str]]) -> str:
        study = {"name": self.faker.pystr(), "description": self.faker.pystr()}
        r = self.client.post(f"{API_URI}/study", headers=headers, json=study)
        assert r.status_code == 200
        uuid = BaseTests.get_content(r)
        assert isinstance(uuid, str)
        self.studies[uuid] = headers
        return uuid

    def track_study(self, uuid: str, headers: Optional[Dict[str, str]]) -> str:
        """Register a study created directly by the test so it is torn down."""
        if uuid:
            self.studies[uuid] = headers
        return uuid

    def track_job(self, uuid: str) -> None:
        """Register a Celery task uuid whose /data/jobs/<uuid> must be removed."""
        if uuid:
            self.job_uuids.append(uuid)

    # ------------------------------------------------------------------ #
    # setup
    # ------------------------------------------------------------------ #
    def setup(self, study: bool = False) -> Any:
        """Create the standard context: group A + user A1, group B + users B1/B2.

        Returns the same tuple historically returned by ``create_test_env`` so
        migrated tests keep the familiar unpacking.
        """
        uuid_group_A = self.create_group()
        user_A1_uuid, user_A1_headers = self.create_user(uuid_group_A)

        uuid_group_B = self.create_group()
        user_B1_uuid, user_B1_headers = self.create_user(uuid_group_B)
        user_B2_uuid, user_B2_headers = self.create_user(uuid_group_B)

        study1_uuid: Optional[str] = None
        study2_uuid: Optional[str] = None
        if study:
            # study1 in group B, study2 in group A (as create_test_env did)
            study1_uuid = self.create_study(user_B1_headers)
            study2_uuid = self.create_study(user_A1_headers)

        return (
            self.admin_headers,
            uuid_group_A,
            user_A1_uuid,
            user_A1_headers,
            uuid_group_B,
            user_B1_uuid,
            user_B1_headers,
            user_B2_uuid,
            user_B2_headers,
            study1_uuid,
            study2_uuid,
        )

    # ------------------------------------------------------------------ #
    # teardown
    # ------------------------------------------------------------------ #
    def _safe_delete(
        self,
        url: str,
        headers: Optional[Dict[str, str]],
        kind: str,
        uuid: str,
        problems: List[str],
    ) -> None:
        # 404 means the test already deleted it: that is a clean state.
        try:
            r = self.client.delete(url, headers=headers)
            if r.status_code not in (204, 404):
                problems.append(
                    f"unexpected status {r.status_code} while deleting {kind} {uuid}"
                )
        except Exception as exc:  # best-effort: never abort remaining cleanup
            problems.append(f"error while deleting {kind} {uuid}: {exc}")

    def teardown(self) -> None:
        problems: List[str] = []

        # Refresh admin token: the test may have invalidated the previous one.
        try:
            self.admin_headers, _ = BaseTests.do_login(self.client, None, None)
        except Exception as exc:
            problems.append(f"admin login failed during teardown: {exc}")

        # 1. Studies first: their deletion cascades datasets/files/phenotypes/
        #    technicals and removes the study input and output directories.
        for uuid, headers in list(self.studies.items()):
            self._safe_delete(
                f"{API_URI}/study/{uuid}", headers, "study", uuid, problems
            )

        # 2. Users (studies must already be gone: user deletion does not cascade).
        for uuid in self.user_uuids:
            self._safe_delete(
                f"{API_URI}/admin/users/{uuid}",
                self.admin_headers,
                "user",
                uuid,
                problems,
            )

        # 3. Group filesystem trees then the group nodes. rmtree is best-effort:
        #    a missing directory (never created, or already removed) is clean.
        for uuid in self.group_uuids:
            shutil.rmtree(INPUT_ROOT.joinpath(uuid), ignore_errors=True)
            shutil.rmtree(OUTPUT_ROOT.joinpath(uuid), ignore_errors=True)
            self._safe_delete(
                f"{API_URI}/admin/groups/{uuid}",
                self.admin_headers,
                "group",
                uuid,
                problems,
            )

        # 4. Pipeline working directories keyed by Celery task uuid.
        for uuid in self.job_uuids:
            shutil.rmtree(JOBS_ROOT.joinpath(uuid), ignore_errors=True)

        # Focused final check: no test-owned filesystem directory must survive.
        for uuid in self.group_uuids:
            if INPUT_ROOT.joinpath(uuid).exists():
                problems.append(f"input directory for group {uuid} still exists")
            if OUTPUT_ROOT.joinpath(uuid).exists():
                problems.append(f"output directory for group {uuid} still exists")
        for uuid in self.job_uuids:
            if JOBS_ROOT.joinpath(uuid).exists():
                problems.append(f"jobs directory for task {uuid} still exists")

        if problems:
            log.warning("Test teardown residues: {}", "; ".join(problems))
            raise AssertionError(
                "Test teardown left residues:\n- " + "\n- ".join(problems)
            )


@pytest.fixture
def test_env(client: FlaskClient, faker: Faker) -> Any:
    """Provide a :class:`TestEnv` and guarantee exception-safe teardown."""
    env = TestEnv(client, faker)
    yield env
    env.teardown()


def create_test_env(client: FlaskClient, faker: Faker, study: bool = False) -> Any:

    # create a group with one user
    uuid_group_A, _ = BaseTests.create_group(client)
    user_A1_uuid, data = BaseTests.create_user(
        client, data={"group": uuid_group_A}, roles=[Role.USER]
    )
    user_A1_headers, _ = BaseTests.do_login(
        client, data.get("email"), data.get("password")
    )

    # create a second group with two users
    uuid_group_B, _ = BaseTests.create_group(client)

    user_B1_uuid, data = BaseTests.create_user(
        client, data={"group": uuid_group_B}, roles=[Role.USER]
    )
    user_B1_headers, _ = BaseTests.do_login(
        client, data.get("email"), data.get("password")
    )

    # create a second user for the group 2
    user_B2_uuid, data = BaseTests.create_user(
        client, data={"group": uuid_group_B}, roles=[Role.USER]
    )
    user_B2_headers, _ = BaseTests.do_login(
        client, data.get("email"), data.get("password")
    )

    study1_uuid = None
    study2_uuid = None
    if study:
        # create a study in group B
        study1 = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(f"{API_URI}/study", headers=user_B1_headers, json=study1)
        assert r.status_code == 200
        study1_uuid = BaseTests.get_content(r)

        # create a study in group A
        study2 = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(f"{API_URI}/study", headers=user_A1_headers, json=study2)
        assert r.status_code == 200
        study2_uuid = BaseTests.get_content(r)

    admin_headers, _ = BaseTests.do_login(client, None, None)

    return (
        admin_headers,
        uuid_group_A,
        user_A1_uuid,
        user_A1_headers,
        uuid_group_B,
        user_B1_uuid,
        user_B1_headers,
        user_B2_uuid,
        user_B2_headers,
        study1_uuid,
        study2_uuid,
    )


def delete_test_env(
    client: FlaskClient,
    user_A1_headers: Tuple[Optional[Dict[str, str]], str],
    user_B1_headers: Tuple[Optional[Dict[str, str]], str],
    user_B1_uuid: str,
    user_B2_uuid: str,
    user_A1_uuid: str,
    uuid_group_A: str,
    uuid_group_B: str,
    study1_uuid: Optional[str] = None,
    study2_uuid: Optional[str] = None,
) -> None:
    """Best-effort, idempotent cleanup kept for tests not yet migrated to the
    ``test_env`` fixture. Every step is attempted even if a previous one fails,
    already-deleted resources (404) are tolerated, and missing directories are
    treated as clean. Problems are collected and reported only at the end."""

    problems: List[str] = []
    admin_headers, _ = BaseTests.do_login(client, None, None)

    def _safe_delete(
        url: str, headers: Optional[Dict[str, str]], kind: str, uuid: str
    ) -> None:
        try:
            r = client.delete(url, headers=headers)
            if r.status_code not in (204, 404):
                problems.append(
                    f"unexpected status {r.status_code} while deleting {kind} {uuid}"
                )
        except Exception as exc:
            problems.append(f"error while deleting {kind} {uuid}: {exc}")

    # delete all the elements used by the test
    if study1_uuid:
        _safe_delete(
            f"{API_URI}/study/{study1_uuid}", user_B1_headers, "study", study1_uuid
        )
    if study2_uuid:
        _safe_delete(
            f"{API_URI}/study/{study2_uuid}", user_A1_headers, "study", study2_uuid
        )
    _safe_delete(
        f"{API_URI}/admin/users/{user_B1_uuid}", admin_headers, "user", user_B1_uuid
    )
    _safe_delete(
        f"{API_URI}/admin/users/{user_B2_uuid}", admin_headers, "user", user_B2_uuid
    )
    _safe_delete(
        f"{API_URI}/admin/users/{user_A1_uuid}", admin_headers, "user", user_A1_uuid
    )

    # group directories: a missing tree is already clean
    shutil.rmtree(INPUT_ROOT.joinpath(uuid_group_A), ignore_errors=True)
    shutil.rmtree(OUTPUT_ROOT.joinpath(uuid_group_A), ignore_errors=True)
    _safe_delete(
        f"{API_URI}/admin/groups/{uuid_group_A}", admin_headers, "group", uuid_group_A
    )
    shutil.rmtree(INPUT_ROOT.joinpath(uuid_group_B), ignore_errors=True)
    shutil.rmtree(OUTPUT_ROOT.joinpath(uuid_group_B), ignore_errors=True)
    _safe_delete(
        f"{API_URI}/admin/groups/{uuid_group_B}", admin_headers, "group", uuid_group_B
    )

    if problems:
        log.warning("Test teardown residues: {}", "; ".join(problems))
        raise AssertionError(
            "Test teardown left residues:\n- " + "\n- ".join(problems)
        )
