from faker import Faker
from nig.tests.setup_tests import create_test_env, delete_test_env
from restapi.connectors import neo4j
from restapi.tests import API_URI, BaseTests, FlaskClient
from restapi.utilities.logs import log


class TestApp(BaseTests):
    def test_api_family(self, client: FlaskClient, faker: Faker) -> None:
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

        # create new phenotypes
        phenotype_father = {
            "name": faker.pystr(),
            "age": faker.pyint(0, 100),
            "sex": "male",
        }
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/phenotypes",
            headers=user_B1_headers,
            data=phenotype_father,
        )
        assert r.status_code == 200
        phenotype_father_uuid = self.get_content(r)
        assert isinstance(phenotype_father_uuid, str)

        phenotype_mother = {
            "name": faker.pystr(),
            "age": faker.pyint(0, 100),
            "sex": "female",
        }
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/phenotypes",
            headers=user_B1_headers,
            data=phenotype_mother,
        )
        assert r.status_code == 200
        phenotype_mother_uuid = self.get_content(r)
        assert isinstance(phenotype_mother_uuid, str)

        phenotype_son_B = {
            "name": faker.pystr(),
            "age": faker.pyint(0, 100),
            "sex": "female",
        }
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/phenotypes",
            headers=user_B1_headers,
            data=phenotype_son_B,
        )
        assert r.status_code == 200
        phenotype_son_B_uuid = self.get_content(r)
        assert isinstance(phenotype_son_B_uuid, str)

        phenotype_son_A = {
            "name": faker.pystr(),
            "age": faker.pyint(0, 100),
            "sex": "female",
        }
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/phenotypes",
            headers=user_A1_headers,
            data=phenotype_son_A,
        )
        assert r.status_code == 200
        phenotype_son_A_uuid = self.get_content(r)
        assert isinstance(phenotype_son_A_uuid, str)

        # create a relationship
        # father case
        r = client.post(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{phenotype_father_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 200
        graph = neo4j.get_instance()
        phenotype_father_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_father_uuid
        )
        phenotype_son_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_son_B_uuid
        )
        assert phenotype_father_node.son.is_connected(phenotype_son_node)
        assert phenotype_son_node.father.is_connected(phenotype_father_node)

        # test relationships in get phenotype list response
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/phenotypes", headers=user_B1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, dict)
        for el in response:
            if el["uuid"] == phenotype_son_B_uuid:
                assert el["relationships"]["father"]["uuid"] == phenotype_father_uuid
            if el["uuid"] == phenotype_father_uuid:
                assert el["relationships"]["sons"][0]["uuid"] == phenotype_son_B_uuid

        # test relationships in get single phenotype response
        r = client.get(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, dict)
        assert response["relationships"]["father"]["uuid"] == phenotype_father_uuid

        r = client.get(
            f"{API_URI}/phenotype/{phenotype_father_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, dict)
        assert response["relationships"]["sons"][0]["uuid"] == phenotype_son_B_uuid

        # create a relationship for two phenotypes in an other study
        r = client.post(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{phenotype_mother_uuid}",
            headers=user_A1_headers,
        )
        assert r.status_code == 404

        # admin creates a relationship
        r = client.post(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{phenotype_mother_uuid}",
            headers=admin_headers,
        )
        assert r.status_code == 404

        # a user of the same group of the owner create a relationship
        # mother case
        r = client.post(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{phenotype_mother_uuid}",
            headers=user_B2_headers,
        )
        assert r.status_code == 200
        graph = neo4j.get_instance()
        phenotype_mother_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_mother_uuid
        )
        phenotype_son_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_son_B_uuid
        )
        assert phenotype_mother_node.son.is_connected(phenotype_son_node)
        assert phenotype_son_node.mother.is_connected(phenotype_mother_node)

        # test relationships in get phenotype list response
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/phenotypes", headers=user_B1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, list)
        for el in response:
            if el["uuid"] == phenotype_son_B_uuid:
                assert el["relationships"]["mother"]["uuid"] == phenotype_mother_uuid
            if el["uuid"] == phenotype_mother_uuid:
                assert el["relationships"]["sons"][0]["uuid"] == phenotype_son_B_uuid

        # test relationships in get single phenotype response
        r = client.get(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, dict)
        assert response["relationships"]["mother"]["uuid"] == phenotype_mother_uuid

        # relationship between phenotype from different studies
        r = client.post(
            f"{API_URI}/phenotype/{phenotype_son_A_uuid}/relationships/{phenotype_father_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 404

        # relationship with a random phenotype as son
        random_phenotype_uuid = faker.pystr()
        r = client.post(
            f"{API_URI}/phenotype/{random_phenotype_uuid}/relationships/{phenotype_father_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 404

        # relationship with a random phenotype as father
        r = client.post(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{random_phenotype_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 404

        # relationship with itself
        r = client.post(
            f"{API_URI}/phenotype/{phenotype_father_uuid}/relationships/{phenotype_father_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 400

        # delete a relationship
        # father case
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{phenotype_father_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 204
        graph = neo4j.get_instance()
        phenotype_father_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_father_uuid
        )
        phenotype_son_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_son_B_uuid
        )
        assert not phenotype_father_node.son.single()
        assert not phenotype_son_node.father.single()

        # delete a relationship for two phenotypes in an other study
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{phenotype_mother_uuid}",
            headers=user_A1_headers,
        )
        assert r.status_code == 404

        # admin delete a relationship
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{phenotype_mother_uuid}",
            headers=admin_headers,
        )
        assert r.status_code == 404

        # a user of the same group of the owner delete a relationship
        # mother case
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{phenotype_mother_uuid}",
            headers=user_B2_headers,
        )
        assert r.status_code == 204
        graph = neo4j.get_instance()
        phenotype_mother_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_mother_uuid
        )
        phenotype_son_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_son_B_uuid
        )
        assert not phenotype_mother_node.son.single()
        assert not phenotype_son_node.mother.single()

        # delete relationship between phenotype from different studies
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype_son_A_uuid}/relationships/{phenotype_father_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 404

        #  delete relationship with a random phenotype as son
        r = client.delete(
            f"{API_URI}/phenotype/{random_phenotype_uuid}/relationships/{phenotype_father_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 404

        # delete relationship with a random phenotype as father
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{random_phenotype_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 404

        r = client.post(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{phenotype_father_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 200

        r = client.post(
            f"{API_URI}/phenotype/{phenotype_son_B_uuid}/relationships/{phenotype_mother_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 200

        # delete a son relationship
        r = client.delete(
            f"{API_URI}/phenotype/{phenotype_mother_uuid}/relationships/{phenotype_son_B_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 204
        graph = neo4j.get_instance()
        phenotype_mother_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_mother_uuid
        )
        phenotype_son_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_son_B_uuid
        )
        assert not phenotype_mother_node.son.single()
        assert not phenotype_son_node.mother.single()

        r = client.delete(
            f"{API_URI}/phenotype/{phenotype_father_uuid}/relationships/{phenotype_son_B_uuid}",
            headers=user_B1_headers,
        )
        assert r.status_code == 204
        graph = neo4j.get_instance()
        phenotype_father_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_father_uuid
        )
        phenotype_son_node = graph.Phenotype.nodes.get_or_none(
            uuid=phenotype_son_B_uuid
        )
        assert not phenotype_father_node.son.single()
        assert not phenotype_son_node.father.single()

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
