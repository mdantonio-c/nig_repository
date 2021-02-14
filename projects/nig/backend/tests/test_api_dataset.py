import json
import os
import shutil
from typing import Any, Dict

from nig.endpoints import GROUP_DIR
from restapi.tests import API_URI, BaseTests


class TestApp(BaseTests):
    def test_api_dataset(self, client, fake):
        admin_headers, _ = self.do_login(client, None, None)
        # create a new group
        new_group_name = fake.pystr()
        new_group_fullname = fake.pystr()
        new_group = {"shortname": new_group_name, "fullname": new_group_fullname}
        r = client.post(
            f"{API_URI}/admin/groups", headers=admin_headers, data=new_group
        )
        assert r.status_code == 200
        new_group_uuid = self.get_content(r)
        # create a second new group
        default_group = {"shortname": fake.pystr(), "fullname": fake.pystr()}
        r = client.post(
            f"{API_URI}/admin/groups", headers=admin_headers, data=default_group
        )
        assert r.status_code == 200
        default_group_uuid = self.get_content(r)

        # create a user for the "default" group
        data: Dict[str, Any] = {}
        data["roles"] = ["normal_user"]
        data["roles"] = json.dumps(data["roles"])
        data["group"] = default_group_uuid
        default_user1_uuid, data = self.create_user(client, data)

        default_user1_header, _ = self.do_login(
            client, data.get("email"), data.get("password")
        )
        # create a second user for the default group
        data = {}
        data["roles"] = ["normal_user"]
        data["roles"] = json.dumps(data["roles"])
        data["group"] = default_group_uuid
        default_user2_uuid, data = self.create_user(client, data)
        default_user2_header, _ = self.do_login(
            client, data.get("email"), data.get("password")
        )

        # create a user for the other group
        data = {}
        data["roles"] = ["normal_user"]
        data["roles"] = json.dumps(data["roles"])
        data["group"] = new_group_uuid
        other_user_uuid, data = self.create_user(client, data)
        other_user_header, _ = self.do_login(
            client, data.get("email"), data.get("password")
        )

        # create a new study for default group
        random_name = fake.pystr()
        study1 = {"name": random_name, "description": fake.pystr()}
        r = client.post(f"{API_URI}/study", headers=default_user1_header, data=study1)
        assert r.status_code == 200
        study1_uuid = self.get_content(r)

        # create a new study for the other group
        random_name2 = fake.pystr()
        study2 = {"name": random_name2, "description": fake.pystr()}
        r = client.post(f"{API_URI}/study", headers=other_user_header, data=study2)
        assert r.status_code == 200
        study2_uuid = self.get_content(r)

        # create a new dataset
        dataset1 = {"name": fake.pystr(), "description": fake.pystr()}
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/datasets",
            headers=default_user1_header,
            data=dataset1,
        )
        assert r.status_code == 200
        dataset1_uuid = self.get_content(r)
        # check the directory exists
        dir_path = os.path.join(
            GROUP_DIR, default_group_uuid, study1_uuid, dataset1_uuid
        )
        assert os.path.isdir(dir_path)

        # create a new dataset in a study of an other group
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/datasets",
            headers=default_user1_header,
            data=dataset1,
        )
        assert r.status_code == 404

        # create a new dataset as admin not belonging to study group
        dataset2 = {"name": fake.pystr(), "description": fake.pystr()}
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/datasets",
            headers=admin_headers,
            data=dataset2,
        )
        assert r.status_code == 404

        r = client.post(
            f"{API_URI}/study/{study1_uuid}/datasets",
            headers=default_user1_header,
            data=dataset2,
        )
        assert r.status_code == 200
        dataset2_uuid = self.get_content(r)

        # test dataset access
        # test dataset list response
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/datasets", headers=default_user1_header
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert len(response) == 2

        # test dataset list response for a study you don't have access
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/datasets", headers=default_user1_header
        )
        assert r.status_code == 404

        # test dataset list response for admin
        r = client.get(f"{API_URI}/study/{study1_uuid}/datasets", headers=admin_headers)
        assert r.status_code == 200
        response = self.get_content(r)
        assert len(response) == 2

        # test empty list of datasets in a study
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/datasets", headers=other_user_header
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert not response

        # dataset owner
        r = client.get(
            f"{API_URI}/dataset/{dataset1_uuid}", headers=default_user1_header
        )
        assert r.status_code == 200
        # same group of the owner
        r = client.get(
            f"{API_URI}/dataset/{dataset1_uuid}", headers=default_user2_header
        )
        assert r.status_code == 200
        # dataset own by an other group
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=other_user_header)
        assert r.status_code == 404
        no_authorized_message = self.get_content(r)

        # admin access
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=admin_headers)
        assert r.status_code == 200

        # test dataset modification
        # modify a dataset you do not own
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=other_user_header,
            data={"description": fake.pystr()},
        )
        assert r.status_code == 404
        # modify a dataset you own
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=default_user1_header,
            data={"description": fake.pystr()},
        )
        assert r.status_code == 204
        # modify a dataset of your group
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=default_user2_header,
            data={"name": fake.pystr()},
        )
        assert r.status_code == 204

        # admin modify a dataset of a group he don't belongs
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=admin_headers,
            data={"description": fake.pystr()},
        )
        assert r.status_code == 404

        # delete a dataset
        # delete a dataset you do not own
        r = client.delete(
            f"{API_URI}/dataset/{dataset1_uuid}", headers=other_user_header
        )
        assert r.status_code == 404
        # admin delete a dataset of a group he don't belong
        r = client.delete(f"{API_URI}/dataset/{dataset1_uuid}", headers=admin_headers)
        assert r.status_code == 404
        # delete a dataset you own
        r = client.delete(
            f"{API_URI}/dataset/{dataset1_uuid}", headers=default_user1_header
        )
        assert r.status_code == 204
        assert not os.path.isdir(dir_path)
        # delete a study own by your group
        r = client.delete(
            f"{API_URI}/dataset/{dataset2_uuid}", headers=default_user2_header
        )
        assert r.status_code == 204
        # check dataset deletion
        r = client.get(
            f"{API_URI}/dataset/{dataset1_uuid}", headers=default_user1_header
        )
        assert r.status_code == 404
        no_existent_message = self.get_content(r)
        assert no_existent_message == no_authorized_message

        # delete all the elements used by the test
        # first study
        r = client.delete(
            f"{API_URI}/study/{study1_uuid}", headers=default_user1_header
        )
        assert r.status_code == 204
        # second study
        r = client.delete(f"{API_URI}/study/{study2_uuid}", headers=other_user_header)
        assert r.status_code == 204
        # first user
        r = client.delete(
            f"{API_URI}/admin/users/{default_user1_uuid}", headers=admin_headers
        )
        assert r.status_code == 204
        # second user
        r = client.delete(
            f"{API_URI}/admin/users/{default_user2_uuid}", headers=admin_headers
        )
        assert r.status_code == 204
        # other user
        r = client.delete(
            f"{API_URI}/admin/users/{other_user_uuid}", headers=admin_headers
        )
        assert r.status_code == 204

        # new group directory
        group_dir_path = os.path.join(GROUP_DIR, new_group_uuid)
        shutil.rmtree(group_dir_path)
        r = client.delete(
            f"{API_URI}/admin/groups/{new_group_uuid}", headers=admin_headers
        )
        assert r.status_code == 204
        # "default" group directory
        group_dir_path = os.path.join(GROUP_DIR, default_group_uuid)
        shutil.rmtree(group_dir_path)
        # "default" group
        r = client.delete(
            f"{API_URI}/admin/groups/{default_group_uuid}", headers=admin_headers
        )
        assert r.status_code == 204
