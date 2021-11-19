from faker import Faker
from nig.endpoints import INPUT_ROOT, OUTPUT_ROOT
from nig.tests import create_test_env, delete_test_env
from restapi.connectors import neo4j
from restapi.tests import API_URI, BaseTests, FlaskClient


class TestApp(BaseTests):
    def test_api_dataset(self, client: FlaskClient, faker: Faker) -> None:
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

        # create a new dataset
        dataset1 = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/datasets",
            headers=user_B1_headers,
            data=dataset1,
        )
        assert r.status_code == 200
        dataset1_uuid = self.get_content(r)
        assert isinstance(dataset1_uuid, str)
        # check the directory exists
        dir_path = INPUT_ROOT.joinpath(uuid_group_B, study1_uuid, dataset1_uuid)
        assert dir_path.is_dir()

        # create a new dataset in a study of an other group
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/datasets",
            headers=user_B1_headers,
            data=dataset1,
        )
        assert r.status_code == 404

        # create a technical
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=user_B1_headers,
            data={"name": faker.pystr()},
        )
        assert r.status_code == 200
        technical_uuid = self.get_content(r)
        assert isinstance(technical_uuid, str)
        # create a phenotype
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/phenotypes",
            headers=user_B1_headers,
            data={"name": faker.pystr(), "sex": "male"},
        )
        assert r.status_code == 200
        phenotype_uuid = self.get_content(r)
        assert isinstance(phenotype_uuid, str)

        # create a new dataset as admin not belonging to study group
        dataset2 = {
            "name": faker.pystr(),
            "description": faker.pystr(),
            "phenotype": phenotype_uuid,
            "technical": technical_uuid,
        }
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
        assert isinstance(dataset2_uuid, str)

        # test dataset access
        # test dataset list response
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/datasets", headers=user_B1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, list)
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
        assert isinstance(response, list)
        assert len(response) == 2

        # test empty list of datasets in a study
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/datasets", headers=user_A1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, list)
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
        not_authorized_message = self.get_content(r)
        assert isinstance(not_authorized_message, str)

        # admin access
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=admin_headers)
        assert r.status_code == 200

        # test technical and phenoype assignation when a new dataset is created
        r = client.get(f"{API_URI}/dataset/{dataset2_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, dict)
        assert "technical" in response
        assert "phenotype" in response
        assert response["technical"]["uuid"] == technical_uuid
        # check phenotype was correctly assigned
        assert response["phenotype"]["uuid"] == phenotype_uuid

        # test dataset changing status
        r = client.patch(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=user_B1_headers,
            data={"status": "UPLOAD COMPLETED"},
        )
        assert r.status_code == 204
        # check new status in get response
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, dict)
        assert "status" in response

        # delete status
        r = client.patch(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=user_B1_headers,
            data={"status": "-1"},
        )
        assert r.status_code == 204
        # check status has been removed
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, dict)
        assert not response["status"]

        # try to modify a status when the dataset is running
        graph = neo4j.get_instance()
        dataset = graph.Dataset.nodes.get_or_none(uuid=dataset1_uuid)
        dataset.status = "RUNNING"
        dataset.save()
        r = client.patch(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=user_B1_headers,
            data={"status": "UPLOAD COMPLETED"},
        )
        assert r.status_code == 400

        # admin tries to modify a status when the dataset is running
        r = client.patch(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=admin_headers,
            data={"status": "UPLOAD COMPLETED"},
        )
        assert r.status_code == 204

        # test dataset modification

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
        # modify a dataset of your group assigning a technical and a phenotype
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=user_B2_headers,
            data={
                "name": faker.pystr(),
                "technical": technical_uuid,
                "phenotype": phenotype_uuid,
            },
        )
        assert r.status_code == 204
        # check technical was correctly assigned
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B2_headers)
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, dict)
        assert "technical" in response
        assert "phenotype" in response
        assert response["technical"]["uuid"] == technical_uuid
        # check phenotype was correctly assigned
        assert response["phenotype"]["uuid"] == phenotype_uuid

        # modify a dataset of your group removing a technical and a phenotype
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=user_B2_headers,
            data={"technical": "-1", "phenotype": "-1"},
        )
        assert r.status_code == 204
        # check technical was correctly removed
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B2_headers)
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, dict)
        assert response["technical"] is None
        # check phenotype was correctly removed
        assert response["phenotype"] is None

        # admin modify a dataset of a group he don't belongs
        r = client.put(
            f"{API_URI}/dataset/{dataset1_uuid}",
            headers=admin_headers,
            data={"description": faker.pystr()},
        )
        assert r.status_code == 404
        # simulate the dataset has an output directory
        # create the output directory in the same way is created in launch pipeline task
        output_path = OUTPUT_ROOT.joinpath(dir_path.relative_to(INPUT_ROOT))
        output_path.mkdir(parents=True)
        assert output_path.is_dir()

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
        assert not dir_path.is_dir()
        # delete a study own by your group
        r = client.delete(f"{API_URI}/dataset/{dataset2_uuid}", headers=user_B2_headers)
        assert r.status_code == 204
        # check dataset deletion
        r = client.get(f"{API_URI}/dataset/{dataset1_uuid}", headers=user_B1_headers)
        assert r.status_code == 404
        not_existent_message = self.get_content(r)
        assert isinstance(not_existent_message, str)
        assert not_existent_message == not_authorized_message
        # check directory deletion
        assert not dir_path.is_dir()
        assert not output_path.is_dir()

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
