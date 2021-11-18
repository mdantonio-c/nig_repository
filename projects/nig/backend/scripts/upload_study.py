import re
import tempfile
from contextlib import contextmanager
from mimetypes import MimeTypes
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Union

import OpenSSL.crypto
import requests
import typer

app = typer.Typer()

POST = "post"
PUT = "put"


@contextmanager
def pfx_to_pem(pfx_path: Path, pfx_password: str) -> Generator[str, None, None]:
    """Decrypts the .pfx file to be used with requests."""
    with tempfile.NamedTemporaryFile(suffix=".pem") as t_pem:
        f_pem = open(t_pem.name, "wb")
        pfx = open(pfx_path, "rb").read()
        p12 = OpenSSL.crypto.load_pkcs12(pfx, pfx_password.encode())
        f_pem.write(
            OpenSSL.crypto.dump_privatekey(
                OpenSSL.crypto.FILETYPE_PEM, p12.get_privatekey()
            )
        )
        f_pem.write(
            OpenSSL.crypto.dump_certificate(
                OpenSSL.crypto.FILETYPE_PEM, p12.get_certificate()
            )
        )
        ca = p12.get_ca_certificates()
        if ca is not None:
            for cert in ca:
                f_pem.write(
                    OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert)
                )
        f_pem.close()
        yield t_pem.name


def request(
    method: str,
    url: str,
    certfile: Path,
    certpwd: str,
    data: Union[bytes, Dict[str, Any]],
    headers: Optional[Dict[str, Any]] = None,
) -> requests.Response:

    with pfx_to_pem(certfile, certpwd) as cert:
        if method == POST:
            return requests.post(
                url,
                data=data,
                headers=headers,
                timeout=30,
                cert=cert,
            )

        if method == PUT:
            return requests.put(
                url,
                data=data,
                headers=headers,
                timeout=30,
                cert=cert,
            )

        return requests.get(
            url,
            headers=headers,
            timeout=30,
            cert=cert,
        )


def error(text: str) -> None:
    typer.secho(text, fg=typer.colors.RED)
    return None


def success(text: str) -> None:
    typer.secho(text, fg=typer.colors.GREEN)
    return None


def get_response(r: requests.Response) -> Any:
    if r.text:
        return r.text
    return r.json()


@app.command()
def upload(
    dataset: Path = typer.Argument(..., help="Path to the dataset"),
    url: str = typer.Option(..., prompt="Server URL", help="Server URL"),
    username: str = typer.Option(..., prompt="Your username"),
    pwd: str = typer.Option(..., prompt="Your password", hide_input=True),
    certfile: Path = typer.Option(
        ..., prompt="Path of your certificate", help="Path of the certificate file"
    ),
    certpwd: str = typer.Option(
        ...,
        prompt="Password of your certificate",
        hide_input=True,
        help="Password of the certifiate",
    ),
    totp: str = typer.Option(..., prompt="2FA TOTP"),
) -> None:

    if not url.startswith("https:"):
        url = f"https://{url}"
    if not url.endswith("/"):
        url = f"{url}/"

    if not certfile.exists():
        return error(f"Certificate not found: {certfile}")

    # check if the input file exists
    if not dataset.exists():
        return error(f"The specified dataset does not exists: {dataset}")

    # Do login
    r = request(
        method=POST,
        url=f"{url}auth/login",
        certfile=certfile,
        certpwd=certpwd,
        data={"username": username, "password": pwd, "totp_code": totp},
    )

    if r.status_code != 200:
        if r.text:
            print(r.text)
            return error(f"Login Failed. Status: {r.status_code}")

        return error(
            f"Login Failed. Status: {r.status_code}, response: {get_response(r)}"
        )

    token = r.json()
    headers = {"Authorization": f"Bearer {token}"}
    success("Succesfully logged in")

    # ####################
    # Find the file into the dataset
    # Temporary faked by assigned dataset to file
    file = dataset
    ##################

    # get the data for the upload request
    filename = file.name
    filesize = file.stat().st_size
    mimeType = MimeTypes().guess_type(str(file))
    lastModified = int(file.stat().st_mtime)

    data = {
        "name": filename,
        "mimeType": mimeType,
        "size": filesize,
        "lastModified": lastModified,
    }

    # init the upload
    r = request(
        method=POST,
        url=f"{url}api/dataset/{dataset}/files/upload",
        headers=headers,
        certfile=certfile,
        certpwd=certpwd,
        data=data,
    )

    if r.status_code != 201:
        resp = get_response(r)
        return error(
            f"Can't start the upload. Status {r.status_code}, response: {resp}"
        )

    success("Upload initialized succesfully")

    chunksize = 16 * 1024 * 1024  # 16 mb
    range_start = 0

    with open(file, "rb") as f:
        with typer.progressbar(length=filesize, label="Uploading") as progress:
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
                r = request(
                    method=PUT,
                    url=f"{url}api/dataset/{dataset}/files/upload/{filename}",
                    headers=headers,
                    certfile=certfile,
                    certpwd=certpwd,
                    data=read_data,
                )

                if r.status_code != 206:
                    if r.status_code == 200:
                        # upload is complete
                        progress.update(filesize)
                        break
                    resp = get_response(r)
                    return error(
                        f"Upload Failed. Status: {r.status_code}, response: {resp}"
                    )
                progress.update(chunksize)
                # update the range variable
                range_start += chunksize
        if r.status_code != 200:
            return error(
                f"Upload Failed. Status: {r.status_code}, response: {get_response(r)}"
            )

        success("Upload finished succesfully")

    return None


if __name__ == "__main__":
    app()


def parse_file_ped(filename: Path) -> None:
    with open(filename) as f:

        # header = None
        for line in f.readlines():

            if line.startswith("#"):
                # Remove the initial #
                line = line[1:].strip().lower()
                # header = re.split(r"\t", line)
                continue

            data = re.split(r"\t", line.strip())

            if len(data) < 5:
                continue

            # pedigree_id = data[0]
            individual_id = data[1]
            father = data[2]
            mother = data[3]
            sex = data[4]
            # + birthday ?
            # + birthplace ?

            if sex == "1":
                sex = "male"
            elif sex == "2":
                sex = "female"

            # 1 Verify if this phenotype already exists?

            # 2 Create the phenotype ...
            properties = {}
            properties["name"] = individual_id
            properties["sex"] = sex
            properties["father"] = father
            properties["mother"] = mother
            ...

            # 3 Connect father and mother, if any

            # 4 Connect to a dataset


def parse_file_tech(filename: Path) -> None:
    with open(filename) as f:

        # header = None
        for line in f.readlines():

            if line.startswith("#"):
                # Remove the initial #
                line = line[1:].strip().lower()
                # header = re.split(r"\t", line)
                continue

            data = re.split(r"\t", line.strip())

            if len(data) < 4:
                continue

            name = data[0]
            date = data[1]
            platform = data[2]
            kit = data[3]
            datasets = data[4]

            # 1 Verify if this technical already exists

            # 2 Create the technical
            properties = {}
            properties["name"] = name
            properties["sequencing_date"] = date
            properties["platform"] = platform
            properties["enrichment_kit"] = kit
            properties["datasets"] = datasets
            ...

            # 3 Connect to datasets
