import json
import os
import shutil

from nig.endpoints import GROUP_DIR, PHENOTYPE_NOT_FOUND, TECHMETA_NOT_FOUND
from restapi.tests import API_URI, BaseTests


class TestApp(BaseTests):
    def test_api_dataset(self, client, faker):
        admin_headers, _ = self.do_login(client, None, None)

        role_list = ["normal_user"]
        role = json.dumps(role_list)

        # create a group with one user
        uuid_group_A, _ = self.create_group(client)
        user_A1_uuid, data = self.create_user(
            client, {"group": uuid_group_A, "roles": role}
        )
        user_A1_headers, _ = self.do_login(
            client, data.get("email"), data.get("password")
        )

        # create a second group with two users
        uuid_group_B, _ = self.create_group(client)

        user_B1_uuid, data = self.create_user(
            client, {"group": uuid_group_B, "roles": role}
        )
        user_B1_headers, _ = self.do_login(
            client, data.get("email"), data.get("password")
        )

        # create a second user for the group 2
        user_B2_uuid, data = self.create_user(
            client, {"group": uuid_group_B, "roles": role}
        )
        user_B2_headers, _ = self.do_login(
            client, data.get("email"), data.get("password")
        )

        # create a study in group B
        study1 = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(f"{API_URI}/study", headers=user_B1_headers, data=study1)
        assert r.status_code == 200
        study1_uuid = self.get_content(r)

        # create a study in group A
        study2 = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(f"{API_URI}/study", headers=user_A1_headers, data=study2)
        assert r.status_code == 200
        study2_uuid = self.get_content(r)

        # create a new dataset
        dataset1 = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/datasets",
            headers=user_B1_headers,
            data=dataset1,
        )
        assert r.status_code == 200
        dataset1_uuid = self.get_content(r)
        # check the directory exists
        dir_path = os.path.join(GROUP_DIR, uuid_group_B, study1_uuid, dataset1_uuid)
        assert os.path.isdir(dir_path)

        # create a new dataset in a study of an other group
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/datasets",
            headers=user_B1_headers,
            data=dataset1,
        )
        assert r.status_code == 404

        # create a new dataset as admin not belonging to study group
        dataset2 = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/datasets",
            headers=admin_headers,
            data=dataset2,
        )
        assert r.status_code == 404

        r = client.post(
            f"{API_URI}/study/{study1_uuid}/datasets",
            headers=user_B1_headers,
            data=dataset2,
        )
        assert r.status_code == 200
        dataset2_uuid = self.get_content(r)

        # test dataset access
        # test dataset list response
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/datasets", headers=user_B1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert len(response) == 2

        # test dataset list response for a study you don't have access
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/datasets", headers=user_B1_headers
        )
        assert r.status_code == 404

        # test dataset list response for admin
        r = client.get(f"{API_URI}/study/{study1_uuid}/datasets", headers=admin_headers)
        assert r.status_code == 200
        response = self.get_content(r)
        assert len(response) == 2

        # test empty list of datasets in a study
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/datasets", headers=user_A1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert not response

        # dataset owner
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        # same group of the owner
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B2_headers)
        assert r.status_code == 200
        # dataset owned by an other group
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_A1_headers)
        assert r.status_code == 404
        no_authorized_message = self.get_content(r)

        # admin access
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=admin_headers)
        assert r.status_code == 200

        # test dataset modification
        # create a technical
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=user_B1_headers,
            data={"name": faker.pystr()},
        )
        assert r.status_code == 200
        technical_uuid = self.get_content(r)

        # modify a dataset you do not own
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=user_A1_headers,
            data={"description": faker.pystr()},
        )
        assert r.status_code == 404
        # modify a dataset you own
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=user_B1_headers,
            data={"description": faker.pystr()},
        )
        assert r.status_code == 204
        # modify a dataset of your group assigning a technical
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=user_B2_headers,
            data={"technical_uuid": technical_uuid},
        )
        assert r.status_code == 204
        # check technical was correctly assigned
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B2_headers)
        assert r.status_code == 200
        response = self.get_content(r)
        assert "technicals" in response[0]
        assert response[0]["technicals"]["uuid"] == technical_uuid
        # modify a dataset of your group removing a technical
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=user_B2_headers,
            data={"technical_uuid": "-1"},
        )
        assert r.status_code == 204
        # check technical was correctly removed
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B2_headers)
        assert r.status_code == 200
        response = self.get_content(r)
        assert "technicals" not in response[0]

        # check assign a technical that does not exists
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=user_B2_headers,
            data={"technical_uuid": faker.pystr()},
        )
        assert r.status_code == 404
        error_msg = self.get_content(r)
        assert error_msg == TECHMETA_NOT_FOUND

        # admin modify a dataset of a group he don't belongs
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=admin_headers,
            data={"description": faker.pystr()},
        )
        assert r.status_code == 404

        # delete a dataset
        # delete a dataset you do not own
        r = client.delete(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_A1_headers)
        assert r.status_code == 404
        # admin delete a dataset of a group he don't belong
        r = client.delete(f"{API_URI}/dataset/{dataset1_uuid}", headers=admin_headers)
        assert r.status_code == 404
        # delete a dataset you own
        r = client.delete(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B1_headers)
        assert r.status_code == 204
        assert not os.path.isdir(dir_path)
        # delete a study own by your group
        r = client.delete(f"{API_URI}/dataset/{dataset2_uuid}", headers=user_B2_headers)
        assert r.status_code == 204
        # check dataset deletion
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B1_headers)
        assert r.status_code == 404
        no_existent_message = self.get_content(r)
        assert no_existent_message == no_authorized_message

        # delete all the elements used by the test
        # first study
        r = client.delete(f"{API_URI}/study/{study1_uuid}", headers=user_B1_headers)
        assert r.status_code == 204
        # second study
        r = client.delete(f"{API_URI}/study/{study2_uuid}", headers=user_A1_headers)
        assert r.status_code == 204
        # first user
        r = client.delete(
            f"{API_URI}/admin/users/{user_B1_uuid}", headers=admin_headers
        )
        assert r.status_code == 204
        # second user
        r = client.delete(
            f"{API_URI}/admin/users/{user_B2_uuid}", headers=admin_headers
        )
        assert r.status_code == 204
        # other user
        r = client.delete(
            f"{API_URI}/admin/users/{user_A1_uuid}", headers=admin_headers
        )
        assert r.status_code == 204

        # new group directory
        group_dir_path = os.path.join(GROUP_DIR, uuid_group_A)
        shutil.rmtree(group_dir_path)
        r = client.delete(
            f"{API_URI}/admin/groups/{uuid_group_A}", headers=admin_headers
        )
        assert r.status_code == 204
        # "default" group directory
        group_dir_path = os.path.join(GROUP_DIR, uuid_group_B)
        shutil.rmtree(group_dir_path)
        # "default" group
        r = client.delete(
            f"{API_URI}/admin/groups/{uuid_group_B}", headers=admin_headers
        )
        assert r.status_code == 204
