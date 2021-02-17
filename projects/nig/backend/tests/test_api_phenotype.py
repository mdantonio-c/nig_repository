from nig.tests.setup_tests import create_test_env, delete_test_env
from restapi.tests import API_URI, BaseTests


class TestApp(BaseTests):
    def test_api_phenotype(self, client, faker):
        # setup the test env
        (
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
        ) = create_test_env(client, faker, study=True)

        # create a new phenotype
        phenotype1 = {
            "name": faker.pystr(),
            "birthday": f"{faker.iso8601()}.000Z",
            "deathday": f"{faker.iso8601()}.000Z",
            "sex": "male",
        }
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/phenotypes",
            headers=user_B1_headers,
            data=phenotype1,
        )
        assert r.status_code == 200
        phenotype1_uuid = self.get_content(r)

        # create a new phenotype in a study of an other group
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/phenotypes",
            headers=user_B1_headers,
            data=phenotype1,
        )
        assert r.status_code == 404

        # create a new phenotype as admin not belonging to study group
        phenotype2 = {
            "name": faker.pystr(),
            "birthday": f"{faker.iso8601()}.000Z",
            "deathday": f"{faker.iso8601()}.000Z",
            "sex": "female",
        }
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/phenotypes",
            headers=admin_headers,
            data=phenotype2,
        )
        assert r.status_code == 404

        r = client.post(
            f"{API_URI}/study/{study1_uuid}/phenotypes",
            headers=user_B1_headers,
            data=phenotype2,
        )
        assert r.status_code == 200
        phenotype2_uuid = self.get_content(r)

        # test phenotype access
        # test phenotype list response
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/phenotypes", headers=user_B1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert len(response) == 2

        # test phenotype list response for a study you don't have access
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/phenotypes", headers=user_B1_headers
        )
        assert r.status_code == 404

        # test phenotype list response for admin
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/phenotypes", headers=admin_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert len(response) == 2

        # test empty list of phenotypes in a study
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/phenotypes", headers=user_A1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert not response

        # study owner
        r = client.get(
            f"{API_URI}/phenotype/{phenotype1_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 200
        # same group of the study owner
        r = client.get(
            f"{API_URI}/phenotype/{phenotype1_uuid}", headers=user_B2_headers
        )
        assert r.status_code == 200
        # phenotype owned by an other group
        r = client.get(
            f"{API_URI}/phenotype/{phenotype1_uuid}", headers=user_A1_headers
        )
        assert r.status_code == 404
        no_authorized_message = self.get_content(r)

        # admin access
        r = client.get(f"{API_URI}/phenotype/{phenotype1_uuid}", headers=admin_headers)
        assert r.status_code == 200

        # test phenotype modification

        # modify a non existent phenotype
        random_phenotype = faker.pystr()
        r = client.put(
            f"{API_URI}/phenotype/{random_phenotype}",
            headers=user_A1_headers,
            data={"name": faker.pystr()},
        )
        assert r.status_code == 404
        # modify a phenotype you do not own
        r = client.put(
            f"{API_URI}/phenotype/{phenotype1_uuid}",
            headers=user_A1_headers,
            data={"name": faker.pystr()},
        )
        assert r.status_code == 404
        # modify a phenotype you own
        r = client.put(
            f"{API_URI}/phenotype/{phenotype1_uuid}",
            headers=user_B1_headers,
            data={
                "deathday": f"{faker.iso8601()}.000Z",
                "birthday": f"{faker.iso8601()}.000Z",
            },
        )
        assert r.status_code == 204

        # admin modify a phenotype of a group he don't belongs
        r = client.put(
            f"{API_URI}/phenotype/{phenotype1_uuid}",
            headers=admin_headers,
            data={"name": faker.pystr()},
        )
        assert r.status_code == 404

        # delete a phenotype
        # delete a phenotype that does not exists
        r = client.delete(
            f"{API_URI}/phenotype/{random_phenotype}", headers=user_A1_headers
        )
        assert r.status_code == 404
        # delete a phenotype in a study you do not own
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype1_uuid}", headers=user_A1_headers
        )
        assert r.status_code == 404
        # admin delete a phenotype of a group he don't belong
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype1_uuid}", headers=admin_headers
        )
        assert r.status_code == 404
        # delete a phenotype in a study you own
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype1_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 204
        # delete a phenotype in a study own by your group
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype2_uuid}", headers=user_B2_headers
        )
        assert r.status_code == 204
        # check phenotype deletion
        r = client.get(
            f"{API_URI}/phenotype/{phenotype1_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 404
        no_existent_message = self.get_content(r)
        assert no_existent_message == no_authorized_message

        # delete all the elements used by the test
        delete_test_env(
            client,
            admin_headers,
            user_A1_headers,
            user_B1_headers,
            user_B1_uuid,
            user_B2_uuid,
            user_A1_uuid,
            uuid_group_A,
            uuid_group_B,
            study1_uuid=study1_uuid,
            study2_uuid=study2_uuid,
        )
