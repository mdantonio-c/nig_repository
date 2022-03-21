from pathlib import Path

from faker import Faker
from nig.endpoints import INPUT_ROOT, OUTPUT_ROOT
from nig.tests import create_test_env, delete_test_env
from restapi.connectors import neo4j
from restapi.tests import API_URI, BaseTests, FlaskClient


class TestApp(BaseTests):
    def test_api_download(self, client: FlaskClient, faker: Faker) -> None:
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

        # test a download from a dataset of another group
        r = client.get(
            f"{API_URI}/dataset/{dataset1_uuid}/download?file=bam",
            headers=user_A1_headers,
        )
        assert r.status_code == 404
        not_authorized_message = self.get_content(r)

        # test a download as an admin
        r = client.get(
            f"{API_URI}/dataset/{dataset1_uuid}/download?file=bam",
            headers=admin_headers,
        )
        assert r.status_code == 404
        assert self.get_content(r) == not_authorized_message

        # test a download of a file with a random extension
        r = client.get(
            f"{API_URI}/dataset/{dataset1_uuid}/download?file={faker.pystr()}",
            headers=user_B1_headers,
        )
        assert r.status_code == 400

        # test a download from a dataset not analyzed
        r = client.get(
            f"{API_URI}/dataset/{dataset1_uuid}/download?file=bam",
            headers=user_B1_headers,
        )
        assert r.status_code == 404
        uncompleted_message = self.get_content(r)
        assert uncompleted_message != not_authorized_message

        # change dataset status
        graph = neo4j.get_instance()
        dataset = graph.Dataset.nodes.get_or_none(uuid=dataset1_uuid)
        dataset.status = "COMPLETED"
        dataset.save()

        # test a download if output dir does not exists
        r = client.get(
            f"{API_URI}/dataset/{dataset1_uuid}/download?file=bam",
            headers=user_B1_headers,
        )
        assert r.status_code == 404
        dir_not_found_message = self.get_content(r)
        assert dir_not_found_message != uncompleted_message

        # create the output dir
        output_path = OUTPUT_ROOT.joinpath(uuid_group_B, study1_uuid, dataset1_uuid)
        output_path.mkdir(parents=True)
        assert output_path.is_dir()

        # create the file
        bam_content = "I am a .bam file"
        filepath = Path(output_path, faker.pystr()).with_suffix(".bam")
        with open(filepath, "w") as f:
            f.write(bam_content)

        # test a download for a file that not exists
        r = client.get(
            f"{API_URI}/dataset/{dataset1_uuid}/download?file=g.vcf",
            headers=user_B1_headers,
        )
        assert r.status_code == 404
        file_not_found_message = self.get_content(r)
        assert file_not_found_message != dir_not_found_message

        # create a second file (to test later if the downloaded file is the requested one)
        gvcf_content = "I am a .g.vcf file"
        filepath = Path(output_path, faker.pystr()).with_suffix(".g.vcf")
        with open(filepath, "w") as f:
            f.write(gvcf_content)

        # an other member of the group downloads a file
        r = client.get(
            f"{API_URI}/dataset/{dataset1_uuid}/download?file=bam",
            headers=user_B2_headers,
        )
        assert r.status_code == 200

        # check the downloaded file is the correct one
        download_content = r.data
        assert download_content.decode("utf-8") == bam_content

        # delete all the element used for the test
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
