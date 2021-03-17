import os
from subprocess import check_call
from typing import Any, Dict

from faker import Faker
from nig.endpoints import GROUP_DIR
from nig.tests.setup_tests import create_test_env, delete_test_env
from requests import Response
from restapi.tests import API_URI, BaseTests, FlaskClient


class TestApp(BaseTests):
    def upload_file(
        self,
        client: FlaskClient,
        headers: Dict[str, str],
        input: str,
        dataset_uuid: str,
        stream: bool = True,
    ) -> Response:
        # get the data for the upload request
        filename = os.path.basename(input)
        filesize = os.path.getsize(input)
        data = {
            "name": filename,
            "mimeType": "application/gzip",
            "size": filesize,
            "lastModified": int(os.path.getmtime(input)),
        }

        r = client.post(
            f"{API_URI}/dataset/{dataset_uuid}/files/upload", headers=headers, data=data
        )
        if r.status_code != 201:
            return r

        chunksize = int(filesize / 2) + 1
        range_start = 0

        with open(input, "rb") as f:
            while True:
                read_data = f.read(chunksize)
                if not read_data:
                    break  # done
                if range_start != 0:
                    range_start += 1
                range_max = range_start + chunksize
                if range_max > filesize:
                    range_max = filesize
                headers["Content-Range"] = f"bytes {range_start}-{range_max}/{filesize}"
                if stream:
                    r = client.put(
                        f"{API_URI}/dataset/{dataset_uuid}/files/upload/{filename}",
                        headers=headers,
                        data=read_data,
                    )
                else:
                    # do not read data to test final size!=expected size
                    r = client.put(
                        f"{API_URI}/dataset/{dataset_uuid}/files/upload/{filename}",
                        headers=headers,
                    )
                if r.status_code != 206:
                    # the upload is completed or an error occurred
                    break
                range_start += chunksize
            return r

    def test_api_file(self, client: FlaskClient, faker: Faker) -> None:
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
        dataset_B = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/datasets",
            headers=user_B1_headers,
            data=dataset_B,
        )
        assert r.status_code == 200
        dataset_B_uuid = self.get_content(r)

        # check accesses for post request
        # upload a new file in a dataset of an other group
        fake_filename = faker.pystr()
        fake_file = {
            "name": f"{fake_filename}.gz",
            "mimeType": "application/gzip",
            "size": faker.pyint(),
            "lastModified": faker.pyint(),
        }
        r = client.post(
            f"{API_URI}/dataset/{dataset_B_uuid}/files/upload",
            headers=user_A1_headers,
            data=fake_file,
        )
        assert r.status_code == 404

        # upload a new file as admin not belonging to study group
        r = client.post(
            f"{API_URI}/dataset/{dataset_B_uuid}/files/upload",
            headers=admin_headers,
            data=fake_file,
        )
        assert r.status_code == 404

        # try to upload a file with a no allowed format
        fake_file = {
            "name": f"{fake_filename}.txt",
            "mimeType": "text/plain",
            "size": faker.pyint(),
            "lastModified": faker.pyint(),
        }
        r = client.post(
            f"{API_URI}/dataset/{dataset_B_uuid}/files/upload",
            headers=user_B1_headers,
            data=fake_file,
        )
        assert r.status_code == 400

        # create a file to upload
        fcontent = faker.paragraph()
        # tmp_basepath=f"/tmp/{fake_filename}"
        # os.mkdir(tmp_basepath)
        with open(f"/tmp/{fake_filename}.txt", "w") as f:
            f.write(fcontent)

        # gzip the new file
        check_call(["gzip", f"/tmp/{fake_filename}.txt"])

        # upload a file
        input = f"/tmp/{fake_filename}.txt.gz"
        response = self.upload_file(
            client, user_B1_headers, input, dataset_B_uuid, stream=True
        )
        assert response.status_code == 200
        # check the file exists and have the expected size
        filename = os.path.basename(input)
        filesize = os.path.getsize(input)
        filepath = os.path.join(
            GROUP_DIR, uuid_group_B, study1_uuid, dataset_B_uuid, filename
        )
        assert os.path.isfile(filepath)
        assert os.path.getsize(filepath) == filesize

        # upload the same file twice
        response = self.upload_file(
            client, user_B2_headers, input, dataset_B_uuid, stream=True
        )
        assert response.status_code == 409

        # upload the same file in a different dataset
        # create a new dataset
        dataset_B2 = {"name": faker.pystr(), "description": faker.pystr()}
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/datasets",
            headers=user_B1_headers,
            data=dataset_B2,
        )
        assert r.status_code == 200
        dataset_B2_uuid = self.get_content(r)
        response = self.upload_file(
            client, user_B2_headers, input, dataset_B2_uuid, stream=True
        )
        assert response.status_code == 200

        # check error if final file size is different from the one expected
        # rename the file to upload
        fake_filename2 = faker.pystr()
        os.rename(input, f"/tmp/{fake_filename2}.txt.gz")
        # upload without streaming
        response = self.upload_file(
            client,
            user_B1_headers,
            f"/tmp/{fake_filename2}.txt.gz",
            dataset_B_uuid,
            stream=False,
        )
        assert response.status_code == 500
        error_message = self.get_content(response)
        assert (
            error_message
            == "File has not been uploaded correctly: final size does not correspond to total size. Please try a new upload"
        )
        # check non complete file has been removed
        filepath2 = os.path.join(
            GROUP_DIR,
            uuid_group_B,
            study1_uuid,
            dataset_B_uuid,
            f"{fake_filename2}.txt.gz",
        )
        assert not os.path.isfile(filepath2)

        # check accesses on put endpoint
        # put on a file in a dataset of an other group
        r = client.put(
            f"{API_URI}/dataset/{dataset_B_uuid}/files/upload/{filename}",
            headers=user_A1_headers,
        )
        assert r.status_code == 404
        # put a file as admin not belonging to study group
        r = client.put(
            f"{API_URI}/dataset/{dataset_B_uuid}/files/upload/{filename}",
            headers=admin_headers,
        )
        assert r.status_code == 404

        # put of a non existent file
        r = client.put(
            f"{API_URI}/dataset/{dataset_B_uuid}/files/upload/{fake_filename2}.txt.gz",
            headers=user_B1_headers,
        )
        assert r.status_code == 404

        # test file access
        # test file list response
        r = client.get(
            f"{API_URI}/dataset/{dataset_B_uuid}/files", headers=user_B1_headers
        )
        assert r.status_code == 200
        file_list = self.get_content(r)
        assert len(file_list) == 1
        file_uuid = file_list[0]["uuid"]

        # test file list response for a dataset you don't have access
        r = client.get(
            f"{API_URI}/dataset/{dataset_B_uuid}/files", headers=user_A1_headers
        )
        assert r.status_code == 404

        # test file list response for admin
        r = client.get(
            f"{API_URI}/dataset/{dataset_B_uuid}/files", headers=admin_headers
        )
        assert r.status_code == 200
        file_list = self.get_content(r)
        assert len(file_list) == 1

        # check use case of file not in the folder
        # rename the file in the folder as it will not be found
        os.rename(filepath, f"{filepath}.tmp")
        r = client.get(
            f"{API_URI}/dataset/{dataset_B_uuid}/files", headers=user_B1_headers
        )
        assert r.status_code == 200
        file_list = self.get_content(r)
        assert file_list[0]["status"] == "unknown"
        # create an empty file with the original name -- test status from unknown to importing
        with open(filepath, "a"):
            os.utime(filepath, None)
        r = client.get(
            f"{API_URI}/dataset/{dataset_B_uuid}/files", headers=user_B1_headers
        )
        assert r.status_code == 200
        file_list = self.get_content(r)
        assert file_list[0]["status"] == "importing"

        # restore the original file
        os.remove(filepath)
        r = client.get(f"{API_URI}/file/{file_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        file_response = self.get_content(r)
        assert file_response["status"] == "unknown"
        os.rename(f"{filepath}.tmp", filepath)

        r = client.get(
            f"{API_URI}/dataset/{dataset_B_uuid}/files", headers=user_B1_headers
        )
        assert r.status_code == 200
        file_list = self.get_content(r)
        assert file_list[0]["status"] == "uploaded"

        # dataset owner
        r = client.get(f"{API_URI}/file/{file_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        # same group of the dataset owner
        r = client.get(f"{API_URI}/file/{file_uuid}", headers=user_B2_headers)
        assert r.status_code == 200
        # file owned by an other group
        r = client.get(f"{API_URI}/file/{file_uuid}", headers=user_A1_headers)
        assert r.status_code == 404
        no_authorized_message = self.get_content(r)

        # admin access
        r = client.get(f"{API_URI}/file/{file_uuid}", headers=admin_headers)
        assert r.status_code == 200

        # check use case of file not in the folder
        # rename the file in the folder as it will not be found
        os.rename(filepath, f"{filepath}.tmp")
        r = client.get(f"{API_URI}/file/{file_uuid}", headers=user_B1_headers)
        assert r.status_code == 200

        # create an empty file with the original name -- test status from unknown to importing
        with open(filepath, "a"):
            os.utime(filepath, None)
        r = client.get(f"{API_URI}/file/{file_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        file_res = self.get_content(r)
        assert file_res["status"] == "importing"

        # restore the original file
        os.remove(filepath)
        r = client.get(f"{API_URI}/file/{file_uuid}", headers=user_B1_headers)
        assert r.status_code == 200

        os.rename(f"{filepath}.tmp", filepath)

        r = client.get(f"{API_URI}/file/{file_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        file_res = self.get_content(r)
        assert file_res["status"] == "uploaded"

        # delete a file
        # delete a file that does not exists
        r = client.delete(f"{API_URI}/file/{fake_filename}", headers=user_A1_headers)
        assert r.status_code == 404
        # delete a file in a dataset you do not own
        r = client.delete(f"{API_URI}/file/{file_uuid}", headers=user_A1_headers)
        assert r.status_code == 404
        # admin delete a file of a dataset he don't belong
        r = client.delete(f"{API_URI}/file/{file_uuid}", headers=admin_headers)
        assert r.status_code == 404
        # delete a file in a dataset you own
        r = client.delete(f"{API_URI}/file/{file_uuid}", headers=user_B1_headers)
        assert r.status_code == 204
        # delete a file in a dataset own by your group
        r = client.get(
            f"{API_URI}/dataset/{dataset_B2_uuid}/files", headers=user_B2_headers
        )
        file_list = self.get_content(r)
        file2_uuid = file_list[0]["uuid"]

        r = client.delete(f"{API_URI}/file/{file2_uuid}", headers=user_B2_headers)
        assert r.status_code == 204
        # check file deletion
        r = client.get(f"{API_URI}/file/{file_uuid}", headers=user_B1_headers)
        assert r.status_code == 404
        no_existent_message = self.get_content(r)
        assert no_existent_message == no_authorized_message
        # check physical deletion from the folder
        assert not os.path.isfile(filepath)

        # delete the file created for the tests
        os.remove(f"/tmp/{fake_filename2}.txt.gz")

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
