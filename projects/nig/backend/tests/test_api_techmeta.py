import json
import os
import shutil

from nig.endpoints import GROUP_DIR, PHENOTYPE_NOT_FOUND, TECHMETA_NOT_FOUND
from restapi.tests import API_URI, BaseTests


class TestApp(BaseTests):
    def test_api_techmeta(self, client, faker):
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

        # create a new techmeta
        techmeta1 = {
            "name": faker.pystr(),
            "sequencing_date": "15/02/2021",
            "platform": "Other",
        }
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=user_B1_headers,
            data=techmeta1,
        )
        assert r.status_code == 200
        techmeta1_uuid = self.get_content(r)

        # create a new techmeta in a study of an other group
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/technicals",
            headers=user_B1_headers,
            data=techmeta1,
        )
        assert r.status_code == 404

        # create a new technical as admin not belonging to study group
        techmeta2 = {
            "name": faker.pystr(),
            "sequencing_date": "15/02/2021",
            "platform": "Other",
        }
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=admin_headers,
            data=techmeta2,
        )
        assert r.status_code == 404

        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=user_B1_headers,
            data=techmeta2,
        )
        assert r.status_code == 200
        techmeta2_uuid = self.get_content(r)

        # test technical access
        # test technical list response
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/technicals", headers=user_B1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert len(response) == 2

        # test technical list response for a study you don't have access
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/technicals", headers=user_B1_headers
        )
        assert r.status_code == 404

        # test technical list response for admin
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/technicals", headers=admin_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert len(response) == 2

        # test empty list of technicals in a study
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/technicals", headers=user_A1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert not response

        # study owner
        r = client.get(f"{API_URI}/technical/{techmeta1_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        # same group of the study owner
        r = client.get(f"{API_URI}/technical/{techmeta1_uuid}", headers=user_B2_headers)
        assert r.status_code == 200
        # technical owned by an other group
        r = client.get(f"{API_URI}/technical/{techmeta1_uuid}", headers=user_A1_headers)
        assert r.status_code == 404
        no_authorized_message = self.get_content(r)

        # admin access
        r = client.get(f"{API_URI}/technical/{techmeta1_uuid}", headers=admin_headers)
        assert r.status_code == 200

        # test technical modification

        # modify a non existent technical
        random_technical = faker.pystr()
        r = client.put(
            f"{API_URI}/technical/{random_technical}",
            headers=user_A1_headers,
            data={"name": faker.pystr()},
        )
        assert r.status_code == 404
        # modify a technical you do not own
        r = client.put(
            f"{API_URI}/technical/{techmeta1_uuid}",
            headers=user_A1_headers,
            data={"name": faker.pystr()},
        )
        assert r.status_code == 404
        # modify a technical you own
        r = client.put(
            f"{API_URI}/technical/{techmeta1_uuid}",
            headers=user_B1_headers,
            data={"name": faker.pystr()},
        )
        assert r.status_code == 204

        # admin modify a technical of a group he don't belongs
        r = client.put(
            f"{API_URI}/technical/{techmeta1_uuid}",
            headers=admin_headers,
            data={"name": faker.pystr()},
        )
        assert r.status_code == 404

        # delete a technical
        # delete a technical that does not exists
        r = client.delete(
            f"{API_URI}/technical/{random_technical}", headers=user_A1_headers
        )
        assert r.status_code == 404
        # delete a technical in a study you do not own
        r = client.delete(
            f"{API_URI}/technical/{techmeta1_uuid}", headers=user_A1_headers
        )
        assert r.status_code == 404
        # admin delete a technical of a group he don't belong
        r = client.delete(
            f"{API_URI}/technical/{techmeta1_uuid}", headers=admin_headers
        )
        assert r.status_code == 404
        # delete a technical in a study you own
        r = client.delete(
            f"{API_URI}/technical/{techmeta1_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 204
        # delete a technical in a study own by your group
        r = client.delete(
            f"{API_URI}/technical/{techmeta2_uuid}", headers=user_B2_headers
        )
        assert r.status_code == 204
        # check technical deletion
        r = client.get(f"{API_URI}/technical/{techmeta1_uuid}", headers=user_B1_headers)
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

        # group A directory
        group_dir_path = os.path.join(GROUP_DIR, uuid_group_A)
        shutil.rmtree(group_dir_path)
        # group A
        r = client.delete(
            f"{API_URI}/admin/groups/{uuid_group_A}", headers=admin_headers
        )
        assert r.status_code == 204
        # group B directory
        group_dir_path = os.path.join(GROUP_DIR, uuid_group_B)
        shutil.rmtree(group_dir_path)
        # group B
        r = client.delete(
            f"{API_URI}/admin/groups/{uuid_group_B}", headers=admin_headers
        )
        assert r.status_code == 204
