from faker import Faker
from nig.endpoints import NIGEndpoint
from nig.tests.setup_tests import create_test_env, delete_test_env
from restapi.connectors import neo4j
from restapi.tests import API_URI, BaseTests, FlaskClient


class TestApp(BaseTests):
    def test_api_stats(self, client: FlaskClient, faker: Faker) -> None:
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
        # create a dataset for group A
        dataset_A = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/datasets",
            headers=user_A1_headers,
            data=dataset_A,
        )
        assert r.status_code == 200
        dataset_A_uuid = self.get_content(r)
        # create a dataset for group B
        dataset_B = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/datasets",
            headers=user_B1_headers,
            data=dataset_B,
        )
        assert r.status_code == 200
        dataset_B_uuid = self.get_content(r)

        # init an upload in dataset A
        fake_filename = faker.pystr()
        fake_file = {
            "name": f"{fake_filename}.gz",
            "mimeType": "application/gzip",
            "size": faker.pyint(),
            "lastModified": faker.pyint(),
        }
        r = client.post(
            f"{API_URI}/dataset/{dataset_A_uuid}/files/upload",
            headers=user_A1_headers,
            data=fake_file,
        )
        assert r.status_code == 201
        # init an upload in dataset B

        r = client.post(
            f"{API_URI}/dataset/{dataset_B_uuid}/files/upload",
            headers=user_B1_headers,
            data=fake_file,
        )
        assert r.status_code == 201

        # test public stats
        r = client.get(
            f"{API_URI}/stats/public",
        )
        assert r.status_code == 200
        public_stats = self.get_content(r)
        assert public_stats["num_users"] == 3
        assert public_stats["num_studies"] == 2
        assert public_stats["num_datasets"] == 2
        assert public_stats["num_files"] == 2

        # test authentication for private stats
        r = client.get(
            f"{API_URI}/stats/private",
        )
        assert r.status_code == 401

        # test private stats
        r = client.get(
            f"{API_URI}/stats/private",
            headers=user_B1_headers,
        )
        private_stats = self.get_content(r)
        assert private_stats["num_users"] == 3
        assert private_stats["num_studies"] == 2
        assert private_stats["num_datasets"] == 2
        assert private_stats["num_files"] == 2
        # get group fullnames
        graph = neo4j.get_instance()
        group_A = graph.Group.nodes.get_or_none(uuid=uuid_group_A)
        group_A_fullname = group_A.fullname
        group_B = graph.Group.nodes.get_or_none(uuid=uuid_group_B)
        group_B_fullname = group_B.fullname
        assert private_stats["num_datasets_per_group"][group_A_fullname] == 1
        assert private_stats["num_datasets_per_group"][group_B_fullname] == 1

        # test stats excluding a group
        NIGEndpoint.GROUPS_TO_FILTER = ["Default group", group_A_fullname]
        # public
        r = client.get(
            f"{API_URI}/stats/public",
        )
        assert r.status_code == 200
        public_stats = self.get_content(r)
        assert public_stats["num_users"] == 2
        assert public_stats["num_studies"] == 1
        assert public_stats["num_datasets"] == 1
        assert public_stats["num_files"] == 1
        # private
        r = client.get(
            f"{API_URI}/stats/private",
            headers=user_B1_headers,
        )
        private_stats = self.get_content(r)
        assert private_stats["num_users"] == 2
        assert private_stats["num_studies"] == 1
        assert private_stats["num_datasets"] == 1
        assert private_stats["num_files"] == 1
        assert group_A_fullname not in private_stats["num_datasets_per_group"]
        assert group_B_fullname in private_stats["num_datasets_per_group"]

        # delete all the elements used by the test
        delete_test_env(
            client,
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
