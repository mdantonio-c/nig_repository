import os
import time
from mimetypes import MimeTypes

import requests
import typer

app = typer.Typer()


@app.command()
def upload(
    input: str = typer.Argument(None, help="path of file to upload"),
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
        typer.echo(
            "ERROR: the specified environment is not valid. Please choose between dev and local"
        )
        return

    # check if the input file exists
    if not os.path.exists(input):
        typer.echo("ERROR: the specified input path does not exists")
        return

    # do login
    r = requests.post(
        f"{url}auth/login", {"username": username, "password": pwd, "totp_code": totp}
    )

    if r.status_code != 200:
        typer.echo(
            f"ERROR: fail to login. Status code: {r.status_code}, response content: {r.json()}"
        )
        return

    token = r.json()
    headers = {"Authorization": f"Bearer {token}"}
    typer.echo("Logged in succesfully")

    # get the data for the upload request
    filename = os.path.basename(input)
    filesize = os.path.getsize(input)
    mimeType = MimeTypes().guess_type(input)
    lastModified = int(os.path.getmtime(input))

    data = {
        "name": filename,
        "mimeType": mimeType,
        "size": filesize,
        "lastModified": lastModified,
    }

    # init the upload

    r = requests.post(
        f"{url}api/dataset/{dataset}/files/upload", headers=headers, data=data
    )
    if r.status_code != 201:
        typer.echo(
            f"ERROR: fail to initialize the upload. Status code: {r.status_code}, response content: {r.json()}"
        )
        return

    typer.echo("Upload initialized succesfully")

    chunksize = 100000  # 1kb
    range_start = 0

    with open(input, "rb") as f:
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
                    url + f"api/dataset/{dataset}/files/upload/{filename}",
                    headers=headers,
                    data=read_data,
                )
                if r.status_code != 206:
                    if r.status_code == 200:
                        # upload is complete
                        progress.update(filesize)
                        break
                    typer.echo(
                        "ERROR: Fail in uploading the file. Status code: {}, response content: {}".format(
                            r.status_code, r.json()
                        )
                    )
                    return
                # update the typer progress bar
                time.sleep(1)
                progress.update(chunksize)
                # update the range variable
                range_start += chunksize
        if r.status_code == 200:
            typer.echo("Upload finished succesfully")
        else:
            typer.echo(
                "ERROR: Fail in uploading the file. Status code: {}, response content: {}".format(
                    r.status_code, r.json()
                )
            )

    return None


if __name__ == "__main__":
    app()
