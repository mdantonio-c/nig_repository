import os
import shutil

from nig.endpoints import GROUP_DIR
from restapi.services.authentication import Role
from restapi.tests import API_URI, BaseTests


def create_test_env(client, faker, study=False):
    admin_headers, _ = BaseTests.do_login(client, None, None)

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
        r = client.post(f"{API_URI}/study", headers=user_B1_headers, data=study1)
        assert r.status_code == 200
        study1_uuid = BaseTests.get_content(r)

        # create a study in group A
        study2 = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(f"{API_URI}/study", headers=user_A1_headers, data=study2)
        assert r.status_code == 200
        study2_uuid = BaseTests.get_content(r)
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
    client,
    admin_headers,
    user_A1_headers,
    user_B1_headers,
    user_B1_uuid,
    user_B2_uuid,
    user_A1_uuid,
    uuid_group_A,
    uuid_group_B,
    study1_uuid=None,
    study2_uuid=None,
):

    # delete all the elements used by the test
    if study1_uuid:
        r = client.delete(f"{API_URI}/study/{study1_uuid}", headers=user_B1_headers)
        assert r.status_code == 204
    if study2_uuid:
        r = client.delete(f"{API_URI}/study/{study2_uuid}", headers=user_A1_headers)
        assert r.status_code == 204
    # first user
    r = client.delete(f"{API_URI}/admin/users/{user_B1_uuid}", headers=admin_headers)
    assert r.status_code == 204
    # second user
    r = client.delete(f"{API_URI}/admin/users/{user_B2_uuid}", headers=admin_headers)
    assert r.status_code == 204
    # other user
    r = client.delete(f"{API_URI}/admin/users/{user_A1_uuid}", headers=admin_headers)
    assert r.status_code == 204

    # group A directory
    group_dir_path = os.path.join(GROUP_DIR, uuid_group_A)
    shutil.rmtree(group_dir_path)
    # group A
    r = client.delete(f"{API_URI}/admin/groups/{uuid_group_A}", headers=admin_headers)
    assert r.status_code == 204
    # group B directory
    group_dir_path = os.path.join(GROUP_DIR, uuid_group_B)
    shutil.rmtree(group_dir_path)
    # group B
    r = client.delete(f"{API_URI}/admin/groups/{uuid_group_B}", headers=admin_headers)
    assert r.status_code == 204
