from faker import Faker
from nig.tests.setup_tests import create_test_env, delete_test_env
from restapi.tests import API_URI, BaseTests, FlaskClient


class TestApp(BaseTests):
    def test_api_techmeta(self, client: FlaskClient, faker: Faker) -> None:
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

        # create a new techmeta
        techmeta1 = {
            "name": faker.pystr(),
            "sequencing_date": f"{faker.iso8601()}.000Z",
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
            "sequencing_date": f"{faker.iso8601()}.000Z",
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
            data={"name": faker.pystr(), "sequencing_date": f"{faker.iso8601()}.000Z"},
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
