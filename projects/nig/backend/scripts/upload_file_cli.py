import time
from mimetypes import MimeTypes
from pathlib import Path

import requests
import typer

app = typer.Typer()


@app.command()
def upload(
    file: Path = typer.Argument(None, help="path of file to upload"),
    username: str = typer.Option(None, prompt=True),
    pwd: str = typer.Option(None, prompt=True, hide_input=True),
    totp: str = typer.Option(None, prompt=True),
    env: str = typer.Option("local", help="choose between local and dev"),
    dataset: str = typer.Option(None, help="dataset uuid"),
) -> None:
    if env == "local":
        url = "http://localhost:8080/"
    elif env == "dev":
        url = "https://nig-dev.cineca.it/"
    else:
        typer.echo("ERROR: Invalid environment, please choose between dev and local")
        return None

    # check if the input file exists
    if not file.exists():
        typer.echo("ERROR: the specified input path does not exists")
        return None

    # do login
    r = requests.post(
        f"{url}auth/login",
        {"username": username, "password": pwd, "totp_code": totp},
        timeout=30,
    )

    if r.status_code != 200:
        typer.echo(
            f"ERROR: fail to login. Status: {r.status_code}, response: {r.json()}"
        )
        return None

    token = r.json()
    headers = {"Authorization": f"Bearer {token}"}
    typer.echo("Logged in succesfully")

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
        typer.echo(
            f"ERROR: can't start the upload. Status {r.status_code}, response: {r.json()}"
        )
        return None

    typer.echo("Upload initialized succesfully")

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
                    typer.echo(
                        f"ERROR: Fail in uploading the file. Status: {r.status_code}, response: {r.json()}"
                    )
                    return None
                # update the typer progress bar
                time.sleep(1)
                progress.update(chunksize)
                # update the range variable
                range_start += chunksize
        if r.status_code == 200:
            typer.echo("Upload finished succesfully")
        else:
            typer.echo(
                f"ERROR: Fail in uploading the file. Status: {r.status_code}, response: {r.json()}"
            )
    return None


if __name__ == "__main__":
    app()
