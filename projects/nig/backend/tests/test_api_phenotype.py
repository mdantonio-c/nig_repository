import json
from typing import Any, Dict

from faker import Faker
from nig.tests.setup_tests import create_test_env, delete_test_env
from restapi.connectors import neo4j
from restapi.tests import API_URI, BaseTests, FlaskClient
from restapi.utilities.logs import log


class TestApp(BaseTests):
    def test_api_phenotype(self, client: FlaskClient, faker: Faker) -> None:
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

        # create a phenotype with a geodata and a list of hpo
        graph = neo4j.get_instance()
        geodata_nodes = graph.GeoData.nodes
        geodata_uuid = geodata_nodes[0].uuid
        hpo_nodes = graph.HPO.nodes
        hpo1_id = hpo_nodes[0].hpo_id
        hpo2_id = hpo_nodes[1].hpo_id
        phenotype2["birth_place"] = geodata_uuid
        phenotype2["hpo"] = [hpo1_id, hpo2_id]
        phenotype2["hpo"] = json.dumps(phenotype2["hpo"])

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
            f"{API_URI}/phenotype/{phenotype2_uuid}", headers=user_B2_headers
        )
        assert r.status_code == 200
        # check hpo and geodata were correctly linked
        response = self.get_content(r)
        assert response["birth_place"]["uuid"] == geodata_uuid
        assert len(response["hpo"]) == 2
        hpo_list = []
        for el in response["hpo"]:
            hpo_list.append(el["hpo_id"])
        assert hpo1_id in hpo_list
        assert hpo2_id in hpo_list

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
            data={"name": faker.pystr(),"sex": "female"},
        )
        assert r.status_code == 404
        # modify a phenotype you do not own
        r = client.put(
            f"{API_URI}/phenotype/{phenotype1_uuid}",
            headers=user_A1_headers,
            data={"name": faker.pystr(),"sex": "female"},
        )
        assert r.status_code == 404
        # modify a phenotype you own
        phenotype1["deathday"] = f"{faker.iso8601()}.000Z"
        phenotype1["birthday"] = f"{faker.iso8601()}.000Z"
        r = client.put(
            f"{API_URI}/phenotype/{phenotype1_uuid}",
            headers=user_B1_headers,
            data=phenotype1,
        )
        assert r.status_code == 204

        # admin modify a phenotype of a group he don't belongs
        r = client.put(
            f"{API_URI}/phenotype/{phenotype1_uuid}",
            headers=admin_headers,
            data={"name": faker.pystr(),"sex": "female"},
        )
        assert r.status_code == 404

        # add a new hpo and change the previous geodata
        hpo3_id = hpo_nodes[2].hpo_id
        geodata2_uuid = geodata_nodes[1].uuid
        phenotype2["name"] = faker.pystr()
        phenotype2["sex"] = "male"
        phenotype2["birth_place"] = geodata2_uuid
        phenotype2["hpo"]=[hpo1_id, hpo2_id,hpo3_id]
        phenotype2["hpo"] = json.dumps(phenotype2["hpo"])
        r = client.put(
            f"{API_URI}/phenotype/{phenotype2_uuid}",
            headers=user_B1_headers,
            data=phenotype2,
        )
        assert r.status_code == 204
        r = client.get(
            f"{API_URI}/phenotype/{phenotype2_uuid}", headers=user_B2_headers
        )
        res = self.get_content(r)
        assert res["birth_place"]["uuid"] == geodata2_uuid
        assert len(res["hpo"]) == 3

        # delete all hpo and geodata
        data: Dict[str, Any] = {**phenotype2}
        data.pop('birth_place', None)
        data.pop('hpo', None)
        r = client.put(
            f"{API_URI}/phenotype/{phenotype2_uuid}", headers=user_B1_headers, data=data
        )
        assert r.status_code == 204
        r = client.get(
            f"{API_URI}/phenotype/{phenotype2_uuid}", headers=user_B2_headers
        )
        response = self.get_content(r)
        assert not response["birth_place"]
        assert not response["hpo"]

        # add a no existing geodata
        phenotype2["birth_place"] = faker.pystr()
        r = client.put(
            f"{API_URI}/phenotype/{phenotype2_uuid}",
            headers=user_B1_headers,
            data=phenotype2,
        )
        assert r.status_code == 400

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
