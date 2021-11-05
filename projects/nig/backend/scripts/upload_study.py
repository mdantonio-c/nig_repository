import tempfile
import time
from contextlib import contextmanager
from mimetypes import MimeTypes
from pathlib import Path
from typing import Any, Dict, Generator, Optional

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
    data: Dict[str, Any],
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


def error(text: str) -> None:
    typer.secho(text, fg=typer.colors.RED)
    return None


def success(text: str) -> None:
    typer.secho(text, fg=typer.colors.GREEN)
    return None


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

        return error(f"Login Failed. Status: {r.status_code}, response: {r.json()}")

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

    r = requests.post(
        f"{url}api/dataset/{dataset}/files/upload",
        headers=headers,
        data=data,
        timeout=30,
    )
    if r.status_code != 201:
        return error(
            f"Can't start the upload. Status {r.status_code}, response: {r.json()}"
        )

    success("Upload initialized succesfully")

    chunksize = 100000  # 1kb
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
                r = requests.put(
                    f"{url}api/dataset/{dataset}/files/upload/{filename}",
                    headers=headers,
                    data=read_data,
                    timeout=30,
                )
                if r.status_code != 206:
                    if r.status_code == 200:
                        # upload is complete
                        progress.update(filesize)
                        break
                    return error(
                        f"Upload Failed. Status: {r.status_code}, response: {r.json()}"
                    )
                # update the typer progress bar
                time.sleep(1)
                progress.update(chunksize)
                # update the range variable
                range_start += chunksize
        if r.status_code != 200:
            return error(
                f"Upload Failed. Status: {r.status_code}, response: {r.json()}"
            )

        success("Upload finished succesfully")

    return None


if __name__ == "__main__":
    app()
