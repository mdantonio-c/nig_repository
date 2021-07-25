import os

from faker import Faker
from nig.endpoints import GROUP_DIR
from nig.tests.setup_tests import create_test_env, delete_test_env
from restapi.tests import API_URI, BaseTests, FlaskClient


class TestApp(BaseTests):
    def test_api_study(self, client: FlaskClient, faker: Faker) -> None:
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
        ) = create_test_env(client, faker, study=False)

        # create a new study for the group B
        random_name = faker.pystr()
        study1 = {"name": random_name, "description": faker.pystr()}
        r = client.post(f"{API_URI}/study", headers=user_B1_headers, data=study1)
        assert r.status_code == 200
        study1_uuid = self.get_content(r)
        assert isinstance(study1_uuid, str)

        # create a new study for the group A
        random_name2 = faker.pystr()
        study2 = {"name": random_name2, "description": faker.pystr()}
        r = client.post(f"{API_URI}/study", headers=user_A1_headers, data=study2)
        assert r.status_code == 200
        study2_uuid = self.get_content(r)
        assert isinstance(study2_uuid, str)

        # check the directory was created
        dir_path = os.path.join(GROUP_DIR, uuid_group_A, study2_uuid)
        assert os.path.isdir(dir_path)

        # test study access
        # test study list response
        r = client.get(f"{API_URI}/study", headers=user_B1_headers)
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, list)
        assert len(response) == 1

        # test admin access
        r = client.get(f"{API_URI}/study/{study1_uuid}", headers=admin_headers)
        assert r.status_code == 200

        # study owner
        r = client.get(f"{API_URI}/study/{study1_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        # other component of the group
        r = client.get(f"{API_URI}/study/{study1_uuid}", headers=user_B2_headers)
        assert r.status_code == 200
        # study own by an other group
        r = client.get(f"{API_URI}/study/{study1_uuid}", headers=user_A1_headers)
        assert r.status_code == 404
        not_authorized_message = self.get_content(r)
        assert isinstance(not_authorized_message, str)

        # test study modification
        # modify a study you do not own
        r = client.put(
            f"{API_URI}/study/{study1_uuid}",
            headers=user_A1_headers,
            data={"description": faker.pystr()},
        )
        assert r.status_code == 404
        # modify a study you own
        r = client.put(
            f"{API_URI}/study/{study1_uuid}",
            headers=user_B1_headers,
            data={"description": faker.pystr()},
        )
        assert r.status_code == 204

        # delete a study
        # delete a study you do not own
        r = client.delete(f"{API_URI}/study/{study1_uuid}", headers=user_A1_headers)
        assert r.status_code == 404
        # delete a study you own
        # create a new dataset to test if it's deleted with the study
        dataset = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/datasets",
            headers=user_A1_headers,
            data=dataset,
        )
        assert r.status_code == 200
        dataset_uuid = self.get_content(r)
        assert isinstance(dataset_uuid, str)
        dataset_path = os.path.join(dir_path, dataset_uuid)
        assert os.path.isdir(dir_path)
        # create a new file to test if it's deleted with the study
        filename = f"{faker.pystr()}_R1"
        file_data = {
            "name": f"{filename}.fastq.gz",
            "mimeType": "application/gzip",
            "size": faker.pyint(),
            "lastModified": faker.pyint(),
        }
        r = client.post(
            f"{API_URI}/dataset/{dataset_uuid}/files/upload",
            headers=user_A1_headers,
            data=file_data,
        )
        assert r.status_code == 201
        # get the file uuid
        r = client.get(
            f"{API_URI}/dataset/{dataset_uuid}/files",
            headers=user_A1_headers,
        )
        assert r.status_code == 200
        file_list = self.get_content(r)
        assert isinstance(file_list, list)
        file_uuid = file_list[0]["uuid"]

        # create a new technical to test if it's deleted with the study
        techmeta = {"name": faker.pystr()}
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/technicals",
            headers=user_A1_headers,
            data=techmeta,
        )
        assert r.status_code == 200
        techmeta_uuid = self.get_content(r)
        assert isinstance(techmeta_uuid, str)
        # create a new phenotype to test if it's deleted with the study
        phenotype = {"name": faker.pystr(), "sex": "male"}
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/phenotypes",
            headers=user_A1_headers,
            data=phenotype,
        )
        assert r.status_code == 200
        phenotype_uuid = self.get_content(r)
        assert isinstance(phenotype_uuid, str)
        # delete the study
        r = client.delete(f"{API_URI}/study/{study2_uuid}", headers=user_A1_headers)
        assert r.status_code == 204
        assert not os.path.isdir(dir_path)
        assert not os.path.isdir(dataset_path)
        # check the dataset was deleted
        r = client.get(f"{API_URI}/dataset/{dataset_uuid}", headers=user_A1_headers)
        assert r.status_code == 404
        # check the file was deleted
        r = client.get(f"{API_URI}/file/{file_uuid}", headers=user_A1_headers)
        assert r.status_code == 404

        # check the technical was deleted
        r = client.get(f"{API_URI}/technical/{techmeta_uuid}", headers=user_A1_headers)
        assert r.status_code == 404
        # check the phenotype was deleted
        r = client.get(f"{API_URI}/phenotype/{phenotype_uuid}", headers=user_A1_headers)
        assert r.status_code == 404

        # delete a study own by your group
        r = client.delete(f"{API_URI}/study/{study1_uuid}", headers=user_B2_headers)
        assert r.status_code == 204
        # check study deletion
        r = client.get(f"{API_URI}/study/{study1_uuid}", headers=user_B1_headers)
        assert r.status_code == 404
        not_existent_message = self.get_content(r)
        assert isinstance(not_existent_message, str)
        assert not_existent_message == not_authorized_message

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
        )
