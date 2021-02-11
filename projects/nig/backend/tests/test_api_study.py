import json
import os
from typing import Any, Dict

from nig.endpoints import GROUP_DIR
from restapi.connectors import neo4j
from restapi.tests import API_URI, BaseTests


class TestApp(BaseTests):
    def test_api_study(self, client, fake):
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

        # create a user for the default group
        graph = neo4j.get_instance()
        default_group = graph.Group.nodes.get_or_none(shortname="Default")
        data: Dict[str, Any] = {}
        data["roles"] = ["normal_user"]
        data["roles"] = json.dumps(data["roles"])
        data["group"] = default_group.uuid
        first_user_uuid, data = self.create_user(client, data)

        first_user_header, _ = self.do_login(
            client, data.get("email"), data.get("password")
        )
        # create a second user for the default group
        data = {}
        data["roles"] = ["normal_user"]
        data["roles"] = json.dumps(data["roles"])
        data["group"] = default_group.uuid
        second_user_uuid, data = self.create_user(client, data)
        second_user_header, _ = self.do_login(
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
        r = client.post(f"{API_URI}/study", headers=first_user_header, data=study1)
        assert r.status_code == 200
        study1_uuid = self.get_content(r)

        # create a new study for the other group
        random_name2 = fake.pystr()
        study2 = {"name": random_name2, "description": fake.pystr()}
        r = client.post(f"{API_URI}/study", headers=other_user_header, data=study2)
        assert r.status_code == 200
        study2_uuid = self.get_content(r)

        # check the directory was created
        dir_path = os.path.join(GROUP_DIR, new_group_uuid, study2_uuid)
        assert os.path.isdir(dir_path)

        # test study access
        # test study list response
        r = client.get(f"{API_URI}/study", headers=first_user_header)
        assert r.status_code == 200
        response = self.get_content(r)
        assert len(response) == 1

        # test admin access
        r = client.get(f"{API_URI}/study/{study1_uuid}", headers=admin_headers)
        assert r.status_code == 200

        # study owner
        r = client.get(f"{API_URI}/study/{study1_uuid}", headers=first_user_header)
        assert r.status_code == 200
        # other component of the group
        r = client.get(f"{API_URI}/study/{study1_uuid}", headers=second_user_header)
        assert r.status_code == 200
        # study own by an other group
        r = client.get(f"{API_URI}/study/{study1_uuid}", headers=other_user_header)
        assert r.status_code == 404
        no_authorized_message = self.get_content(r)

        # test study modification
        # modify a study you do not own
        r = client.put(
            f"{API_URI}/study/{study1_uuid}",
            headers=other_user_header,
            data={"description": fake.pystr()},
        )
        assert r.status_code == 404
        # modify a study you own
        r = client.put(
            f"{API_URI}/study/{study1_uuid}",
            headers=first_user_header,
            data={"description": fake.pystr()},
        )
        assert r.status_code == 204

        # delete a study
        # delete a study you do not own
        r = client.delete(f"{API_URI}/study/{study1_uuid}", headers=other_user_header)
        assert r.status_code == 404
        # delete a study you own
        r = client.delete(f"{API_URI}/study/{study2_uuid}", headers=other_user_header)
        assert r.status_code == 204
        assert not os.path.isdir(dir_path)
        # delete a study own by your group
        r = client.delete(f"{API_URI}/study/{study1_uuid}", headers=second_user_header)
        assert r.status_code == 204
        # check study deletion
        r = client.get(f"{API_URI}/study/{study1_uuid}", headers=first_user_header)
        assert r.status_code == 404
        no_existent_message = self.get_content(r)
        assert no_existent_message == no_authorized_message

        # delete all the elements used by the test
        # first user
        r = client.delete(
            f"{API_URI}/admin/users/{first_user_uuid}", headers=admin_headers
        )
        assert r.status_code == 204
        # second user
        r = client.delete(
            f"{API_URI}/admin/users/{second_user_uuid}", headers=admin_headers
        )
        assert r.status_code == 204
        # other user
        r = client.delete(
            f"{API_URI}/admin/users/{other_user_uuid}", headers=admin_headers
        )
        assert r.status_code == 204
        # new group
        r = client.delete(
            f"{API_URI}/admin/groups/{new_group_uuid}", headers=admin_headers
        )
        assert r.status_code == 204
