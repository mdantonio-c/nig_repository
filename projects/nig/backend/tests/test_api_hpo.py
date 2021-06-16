from faker import Faker
from restapi.tests import API_URI, BaseTests, FlaskClient


class TestApp(BaseTests):
    def test_api_hpo(self, client: FlaskClient, faker: Faker) -> None:

        endpoint = f"{API_URI}/hpo"
        r = client.get(f"{endpoint}/ab")
        assert r.status_code == 401

        headers, _ = self.do_login(client, None, None)

        r = client.get(f"{endpoint}/ab", headers=headers)
        assert r.status_code == 200
        content = self.get_content(r)
        assert isinstance(content, list)
        assert len(list) > 0
        assert isinstance(content[0], dict)
        assert "hpo_id" in content[0]
        assert "label" in content[0]

        r = client.get(f"{endpoint}/abcdefghilmn", headers=headers)
        assert r.status_code == 200
        content = self.get_content(r)
        assert len(content) == 0

        r = client.get(f"{endpoint}/1", headers=headers)
        assert r.status_code == 200
        content = self.get_content(r)
        assert len(content) > 0

        r = client.get(f"{endpoint}/HP:00", headers=headers)
        assert r.status_code == 200
        content = self.get_content(r)
        assert len(content) > 0

        r = client.get(f"{endpoint}/-", headers=headers)
        assert r.status_code == 200
        content = self.get_content(r)
        assert len(content) > 0

        r = client.get(f"{endpoint}/a ", headers=headers)
        assert r.status_code == 200
        content = self.get_content(r)
        assert len(content) > 0
        r = client.get(f"{endpoint}/abc 123 - def : 456", headers=headers)
        assert r.status_code == 200
        content = self.get_content(r)
        assert len(content) == 0

        r = client.get(f"{endpoint}/a(a", headers=headers)
        assert r.status_code == 400

        r = client.get(f"{endpoint}/a)a", headers=headers)
        assert r.status_code == 400

        r = client.get(f"{endpoint}/a'a", headers=headers)
        assert r.status_code == 400

        r = client.get(f'{endpoint}/a"a', headers=headers)
        assert r.status_code == 400

        r = client.get(f"{endpoint}/a#a", headers=headers)
        assert r.status_code == 400
