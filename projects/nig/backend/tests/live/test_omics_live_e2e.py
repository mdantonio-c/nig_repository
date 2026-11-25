"""Live end-to-end run against a real Omics environment (WRITES to Omics).

Uploads two real FASTQ files, submits the NIG germline tool, polls the task,
validates and downloads the outputs as ``omics_fetch_results`` would, observes
the remote cleanup and finally removes what the test uploaded.

Never runs by accident: besides the credentials it needs the explicit opt-in
``OMICS_TEST_E2E=1`` and ``OMICS_TEST_FASTQ_DIR`` (a directory, readable in
the container, containing exactly the two paired ``*.f*q.gz`` files; sorted by
name, the first is R1). Run from the host, typing the password yourself:

    docker cp <fastq-dir> nig-backend-1:/tmp/omics_live_fastq
    read -rsp "Password Omics: " OMICS_TEST_PASSWORD; echo; export OMICS_TEST_PASSWORD
    export OMICS_TEST_BASE_URL=https://omics.dev2.cineca.it/api/v1/ \\
        OMICS_TEST_USERNAME=<service-account> OMICS_TEST_E2E=1 \\
        OMICS_TEST_FASTQ_DIR=/tmp/omics_live_fastq
    docker exec --user developer -e OMICS_TEST_BASE_URL -e OMICS_TEST_USERNAME \\
        -e OMICS_TEST_PASSWORD -e OMICS_TEST_E2E -e OMICS_TEST_FASTQ_DIR \\
        nig-backend-1 sh -c 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/miniconda3/bin restapi tests --wait --no-destroy --folder custom/live'
    unset OMICS_TEST_PASSWORD

Optional: ``OMICS_TEST_E2E_TIMEOUT_MIN`` (task poll timeout, default 60),
``OMICS_TEST_E2E_POLL_SECONDS`` (default 30), ``OMICS_TEST_E2E_CLEANUP_WAIT``
(seconds to wait for Omics to drop downloaded outputs, default 120),
``OMICS_TEST_E2E_KEEP=1`` (keep the remote files), ``OMICS_TEST_E2E_REPORT``
(default ``/tmp/omics_live_e2e.json``).

The report holds remote ids (needed to resume or clean up by hand) but never
tokens or passwords. If the task is still running at the timeout, the inputs
are kept and its id is in the report: check it later with
``OMICS_TEST_TASK_ID`` and the contract test.
"""

import base64
import gzip
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pytest

from nig.services.omics import OmicsClient
from nig.services.omics.errors import OmicsError, OmicsRequestError
from nig.tasks.omics_fetch_results import _expected_outputs, _kind

OMICS_TEST_BASE_URL = os.environ.get("OMICS_TEST_BASE_URL")
OMICS_TEST_USERNAME = os.environ.get("OMICS_TEST_USERNAME")
OMICS_TEST_PASSWORD = os.environ.get("OMICS_TEST_PASSWORD")
E2E_ENABLED = os.environ.get("OMICS_TEST_E2E") == "1"
FASTQ_DIR = os.environ.get("OMICS_TEST_FASTQ_DIR")
TIMEOUT_MIN = int(os.environ.get("OMICS_TEST_E2E_TIMEOUT_MIN", "60"))
POLL_SECONDS = int(os.environ.get("OMICS_TEST_E2E_POLL_SECONDS", "30"))
CLEANUP_WAIT = int(os.environ.get("OMICS_TEST_E2E_CLEANUP_WAIT", "120"))
KEEP_REMOTE = os.environ.get("OMICS_TEST_E2E_KEEP") == "1"
REPORT_PATH = Path(os.environ.get("OMICS_TEST_E2E_REPORT", "/tmp/omics_live_e2e.json"))
TERMINAL_STATUSES = {"complete", "error"}
KNOWN_TASK_STATUSES = {"pending", "received", "processing", "complete", "error"}
# gVCF, BAM and the tabix index (TBI) are all BGZF-compressed; the BAM index
# (BAI) is a separate plain binary format with its own magic bytes.
BGZF_MAGIC = b"\x1f\x8b"
BAI_MAGIC = b"BAI\x01"

pytestmark = pytest.mark.skipif(
    not (
        OMICS_TEST_BASE_URL
        and OMICS_TEST_USERNAME
        and OMICS_TEST_PASSWORD
        and E2E_ENABLED
        and FASTQ_DIR
    ),
    reason=(
        "live Omics E2E skipped: needs OMICS_TEST_BASE_URL / USERNAME / PASSWORD, "
        "OMICS_TEST_E2E=1 and OMICS_TEST_FASTQ_DIR (it uploads and runs a task)"
    ),
)


class LiveRun:
    """Remote state created by this module, always cleaned up at the end."""

    def __init__(self, client: OmicsClient, fastqs: List[Path]) -> None:
        self.client = client
        self.fastqs = fastqs
        self.run_id = uuid.uuid4().hex[:12]
        name = fastqs[0].name
        for suffix in (".fastq.gz", ".fq.gz"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        for marker in ("_R1", "_1"):
            if name.endswith(marker):
                name = name[: -len(marker)]
        self.sample = name
        self.tags = ["nig", "live-test", self.run_id]
        self.input_ids: List[str] = []
        self.output_ids: List[str] = []
        # remote names of inputs then outputs, aligned with input_ids + output_ids
        self.names: List[str] = []
        self.task_id: Optional[str] = None
        self.task_status: Optional[str] = None
        self.report: Dict[str, Any] = {
            "base_url": OMICS_TEST_BASE_URL,
            "run_id": self.run_id,
            "sample": self.sample,
        }

    def remote_name(self, read: int) -> str:
        # same shape as run_batch: unique prefix + NIG FASTQ name
        return f"{self.run_id}_{self.sample}_R{read}.fastq.gz"

    def save(self) -> None:
        REPORT_PATH.write_text(
            json.dumps(self.report, indent=2, sort_keys=True, default=str)
        )

    def matches(self, ids: List[str], names: List[str]) -> Dict[str, Any]:
        """Where our files appear in /files/uploaded, by id and by name.

        The spec calls listed ids "encrypted": they may differ between calls,
        so the name is recorded too.
        """
        items = self.client.list_uploaded_files()
        listed_ids = {str(item.get("file_id")) for item in items}
        by_name = {
            str(item.get("user_filename")): str(item.get("file_id"))
            for item in items
            if str(item.get("user_filename")) in names
        }
        return {
            "listed_count": len(items),
            "by_id": [file_id in listed_ids for file_id in ids],
            "by_name": [name in by_name for name in names],
            "listed_id_equals_ours": [
                by_name.get(name) == file_id for file_id, name in zip(ids, names)
            ],
            "listed_id_prefix_equals_ours": [
                (by_name.get(name) or "").split("::")[0] == file_id.split("::")[0]
                for file_id, name in zip(ids, names)
            ],
        }

    def probe(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Raw call summary (status, payload shape), never raising."""
        try:
            response = self.client._request(method, path, **kwargs)
        except OmicsRequestError as exc:
            return {"status": exc.status_code}
        except OmicsError as exc:
            return {"error": type(exc).__name__}
        info: Dict[str, Any] = {"status": response.status_code, "bytes": len(response.content)}
        try:
            payload = response.json() if response.content else None
        except ValueError:
            return info
        info["type"] = type(payload).__name__
        if isinstance(payload, dict):
            info["keys"] = sorted(payload)
            info["lengths"] = {
                key: len(value) for key, value in payload.items() if isinstance(value, list)
            }
        elif isinstance(payload, list):
            info["length"] = len(payload)
        return info

    def user_id(self) -> Optional[str]:
        # the ``sub`` claim of our own access token; the token is not recorded
        tokens = self.client._auth.tokens
        if tokens is None:
            return None
        try:
            part = tokens.access_token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        except (IndexError, ValueError):
            return None
        sub = claims.get("sub") if isinstance(claims, dict) else None
        return str(sub) if sub else None

    def cleanup(self) -> None:
        cleanup: Dict[str, Any] = {"kept": KEEP_REMOTE}
        self.report["cleanup"] = cleanup
        if KEEP_REMOTE:
            return
        if self.task_id and self.task_status not in TERMINAL_STATUSES:
            # deleting the inputs could break a task still running
            cleanup["kept_inputs_task_not_terminal"] = self.task_status
            return
        # only ids returned to this run (inputs uploaded, outputs of our task)
        targets = list(self.input_ids) + list(self.output_ids)
        deleted: Dict[str, Any] = {}
        for file_id in targets:
            try:
                deleted[file_id] = self.client.delete_file(file_id)
            except OmicsRequestError as exc:
                deleted[file_id] = {"status_code": exc.status_code}
            except OmicsError as exc:
                deleted[file_id] = {"error": type(exc).__name__}
        cleanup["deleted"] = deleted
        cleanup["tags_after_delete"] = [
            self.probe("GET", f"/files/{file_id}/tags") for file_id in targets
        ]
        cleanup["second_delete"] = [
            self.probe("DELETE", f"/storage/objects/{file_id}") for file_id in targets
        ]
        try:
            cleanup["listing"] = self.matches(targets, self.names)
        except OmicsError as exc:
            cleanup["relist_error"] = type(exc).__name__


def _fastqs() -> List[Path]:
    assert FASTQ_DIR is not None
    files = sorted(
        path
        for path in Path(FASTQ_DIR).iterdir()
        if path.is_file() and path.name.endswith((".fastq.gz", ".fq.gz"))
    )
    assert len(files) == 2, f"expected 2 paired FASTQ in {FASTQ_DIR}, found {files}"
    for path in files:
        with gzip.open(path, "rt") as stream:
            assert stream.readline().startswith("@"), f"{path.name} is not a FASTQ"
    return files

@pytest.fixture(scope="module")
def live_run() -> Iterator[LiveRun]:
    assert OMICS_TEST_BASE_URL is not None
    assert OMICS_TEST_USERNAME is not None
    assert OMICS_TEST_PASSWORD is not None
    client = OmicsClient(
        base_url=OMICS_TEST_BASE_URL,
        username=OMICS_TEST_USERNAME,
        password=OMICS_TEST_PASSWORD,
        timeout=60,
    )
    run = LiveRun(client, _fastqs())
    try:
        yield run
    finally:
        try:
            run.cleanup()
        finally:
            run.save()


def test_live_upload_listing_and_resume_probe(live_run: LiveRun) -> None:
    client = live_run.client
    usage = client.get_storage_usage()
    live_run.report["storage_before"] = {
        "usage": usage.usage,
        "quota": usage.quota,
        "limit": usage.limit,
        "can_upload": usage.can_upload,
    }
    assert usage.can_upload, "Omics refuses uploads for this account"

    for read, path in enumerate(live_run.fastqs, start=1):
        file_id = client.upload_file(
            path, tags=live_run.tags, remote_filename=live_run.remote_name(read)
        )
        assert file_id
        live_run.input_ids.append(file_id)
        live_run.names.append(live_run.remote_name(read))
    live_run.save()

    # Diagnostics only: the listing contract is still being aligned with Omics
    # (right after upload /files/uploaded was empty), it must not block submit.
    names = list(live_run.names)
    ids = list(live_run.input_ids)
    user_id = live_run.user_id()
    visibility: Dict[str, Any] = {"user_id_from_token": user_id is not None}
    live_run.report["input_visibility"] = visibility
    attempts: List[Dict[str, Any]] = []
    visibility["files_uploaded"] = attempts
    for attempt in range(4):
        if attempt:
            time.sleep(5)
        attempts.append(
            {"raw": live_run.probe("GET", "/files/uploaded"), **live_run.matches(ids, names)}
        )
        if all(attempts[-1]["by_name"]):
            break
    visibility["storage_after_upload"] = client.get_storage_usage().usage
    visibility["current_uploads"] = live_run.probe("GET", "/storage/upload/current_uploads/")
    visibility["check_file_exists"] = []
    for name in names:
        try:
            data = client._request(
                "GET", "/storage/check_file_exists", params={"filename": name}
            ).json()
            visibility["check_file_exists"].append(
                {
                    "file_exists": data.get("file_exists"),
                    "same_id": data.get("file_id") in ids,
                }
            )
        except (OmicsError, ValueError, AttributeError) as exc:
            visibility["check_file_exists"].append({"error": repr(exc)[:200]})
    visibility["tags"] = [live_run.probe("GET", f"/files/{i}/tags") for i in ids]
    visibility["file_users"] = [live_run.probe("GET", f"/files/{i}/users") for i in ids]
    if user_id:
        visibility["user_files"] = live_run.probe("GET", f"/users/{user_id}/files")
    items = client.list_uploaded_files()
    visibility["listed_entries"] = [
        {key: value for key, value in item.items() if key != "file_id"}
        for item in items
        if item.get("user_filename") in names
    ]
    live_run.save()

    # resume semantics: same name after completion, and a session opened twice
    uploader = client._uploader
    probe: Dict[str, Any] = {}
    opened: List[str] = []
    for label, filename in (
        ("same_name_after_complete", live_run.remote_name(1)),
        ("new_name_first_start", f"{live_run.run_id}_resume_probe.fastq.gz"),
        ("new_name_second_start", f"{live_run.run_id}_resume_probe.fastq.gz"),
    ):
        try:
            session = uploader.start(filename, 1024, tags=live_run.tags)
        except OmicsRequestError as exc:
            probe[label] = {"status_code": exc.status_code}
            continue
        opened.append(session.upload_id)
        probe[label] = {
            "resuming": session.resuming,
            "uploaded_parts": len(session.uploaded_parts),
            "recommended_chunk_size": session.recommended_chunk_size,
            "same_upload_id_as_previous": len(opened) > 1
            and opened[-1] == opened[-2],
        }
    for upload_id in dict.fromkeys(opened):
        try:
            uploader.abort(upload_id)
        except OmicsRequestError as exc:
            probe.setdefault("abort_errors", []).append(exc.status_code)
    probe["inputs_after_abort"] = {
        "tags": live_run.probe("GET", f"/files/{live_run.input_ids[0]}/tags"),
        **live_run.matches(ids, names),
    }
    live_run.report["resume_probe"] = probe
    live_run.save()


@pytest.mark.timeout(TIMEOUT_MIN * 60 + CLEANUP_WAIT + 900)
def test_live_germline_submit_poll_and_fetch(
    live_run: LiveRun, tmp_path: Path
) -> None:
    if len(live_run.input_ids) != 2:
        pytest.skip("inputs not uploaded")
    client = live_run.client
    output_gvcf = f"{live_run.sample}_{live_run.run_id}.g.vcf.gz"
    expected_sample = output_gvcf[: -len(".g.vcf.gz")]

    # The ids returned by upload differ from those listed in /files/uploaded
    # (re-encrypted per response): if the upload ids are rejected, record why
    # and try the listed ones, to learn which the tool accepts.
    attempts: Dict[str, Any] = {}
    live_run.report["submit_attempts"] = attempts
    response: Optional[Dict[str, Any]] = None
    last_error: Optional[OmicsRequestError] = None
    for label in ("upload_ids", "listed_ids"):
        if label == "upload_ids":
            input_ids = list(live_run.input_ids)
        else:
            by_name = {
                str(item.get("user_filename")): str(item.get("file_id"))
                for item in client.list_uploaded_files()
            }
            input_ids = [by_name.get(name, "") for name in live_run.names[:2]]
            if not all(input_ids):
                attempts[label] = {"skipped": "inputs not listed"}
                break
        try:
            response = client.submit_nig_germline(input_ids, output_gvcf=output_gvcf)
        except OmicsRequestError as exc:
            attempts[label] = {"status_code": exc.status_code, "error": str(exc)}
            live_run.save()
            if exc.status_code != 422:
                raise
            last_error = exc
            continue
        attempts[label] = {"accepted": True}
        break
    if response is None:
        assert last_error is not None
        raise last_error
    live_run.report["submit"] = {"keys": sorted(response), "output_gvcf": output_gvcf}
    task_id = response.get("task_id")
    assert task_id, f"submit response without task_id: {sorted(response)}"
    live_run.task_id = str(task_id)
    live_run.report["task_id"] = live_run.task_id
    live_run.save()

    statuses: List[str] = []
    poll: Dict[str, Any] = {"statuses": statuses}
    live_run.report["poll"] = poll
    started = time.monotonic()
    deadline = started + TIMEOUT_MIN * 60
    task = client.get_task(live_run.task_id)
    while True:
        status = str(task.status).lower()
        live_run.task_status = status
        if not statuses or statuses[-1] != status:
            statuses.append(status)
            live_run.save()
        # Error + cleanup_pending is not final: Omics recovery may complete it
        cleanup_pending = isinstance(task.parameters, dict) and bool(
            task.parameters.get("cleanup_pending")
        )
        if (
            status in TERMINAL_STATUSES and not cleanup_pending
        ) or time.monotonic() >= deadline:
            break
        time.sleep(POLL_SECONDS)
        task = client.get_task(live_run.task_id)
    parameters = task.parameters if isinstance(task.parameters, dict) else {}
    poll.update(
        {
            "waited_seconds": int(time.monotonic() - started),
            "start": task.start,
            "end": task.end,
            "elapsed_time": task.elapsed_time,
            "parameter_keys": sorted(parameters),
            "parameters_output_gvcf": parameters.get("output_gvcf"),
        }
    )
    live_run.save()

    assert set(statuses) <= KNOWN_TASK_STATUSES, f"unknown task status: {statuses}"
    assert live_run.task_status == "complete", (
        f"task ended as {live_run.task_status!r} after {poll['waited_seconds']}s"
    )

    outputs = client.get_task_files(live_run.task_id)
    for item in outputs:
        if item.get("file_id"):
            live_run.output_ids.append(str(item["file_id"]))
            live_run.names.append(str(item.get("user_filename")))
    fetch: Dict[str, Any] = {
        "outputs": [
            {
                "kind": item.get("_kind"),
                "user_filename": item.get("user_filename"),
                "size": item.get("size"),
                "keys": sorted(item),
            }
            for item in outputs
        ]
    }
    live_run.report["fetch"] = fetch
    live_run.save()

    try:
        retained = _expected_outputs(outputs)
    except OmicsError as exc:
        fetch["fetch_rejects"] = str(exc)
        live_run.save()
        raise
    gvcf = next(item for item in retained if _kind(item) == "GVCF")
    fetch["gvcf_name_equals_output_gvcf"] = gvcf["user_filename"] == output_gvcf
    retained_ids = [str(item["file_id"]) for item in retained]
    retained_names = [str(item["user_filename"]) for item in retained]
    fetch["outputs_listed_before_download"] = live_run.matches(retained_ids, retained_names)

    downloaded: Dict[str, int] = {}
    for item in retained:
        destination = tmp_path / str(item["user_filename"])
        client.download_file(
            str(item["file_id"]), destination, expected_size=int(item["size"])
        )
        # gVCF, BAM and TBI are BGZF; BAI (BAM index) has its own magic instead.
        kind = _kind(item)
        expected_magic = BAI_MAGIC if kind == "BAI" else BGZF_MAGIC
        magic = destination.read_bytes()[: len(expected_magic)]
        assert magic == expected_magic, destination.name
        downloaded[kind] = destination.stat().st_size
    fetch["downloaded_sizes"] = downloaded
    gvcf_path = tmp_path / str(gvcf["user_filename"])
    samples: List[str] = []
    with gzip.open(gvcf_path, "rt") as stream:
        fetch["gvcf_header_ok"] = stream.readline().startswith("##fileformat=VCF")
        # the agreed output is a per-sample gVCF: it must carry reference blocks
        fetch["gvcf_is_gvcf"] = False
        for line in stream:
            if not line.startswith("#"):
                break
            if line.startswith("##GVCFBlock") or "<NON_REF>" in line:
                fetch["gvcf_is_gvcf"] = True
            if line.startswith("#CHROM"):
                samples = line.rstrip("\n").split("\t")[9:]
    if shutil.which("bcftools"):
        listed = subprocess.run(
            ["bcftools", "query", "-l", str(gvcf_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        samples = listed.stdout.split()
    fetch["gvcf_samples"] = samples
    fetch["gvcf_sample_equals_expected"] = samples == [expected_sample]
    live_run.save()
    assert fetch["gvcf_header_ok"]
    assert fetch["gvcf_is_gvcf"]
    assert fetch["gvcf_sample_equals_expected"], samples

    # Omics retains outputs after download: NIG deletes every locally verified
    # artifact using the id from ``/files/proc/{task_id}``. Listing cannot prove
    # cleanup because task outputs are absent from ``/files/uploaded``.
    fetch["output_tags_before_delete"] = [
        live_run.probe("GET", f"/files/{file_id}/tags") for file_id in retained_ids
    ]
    fetch["output_delete_results"] = [client.delete_file(file_id) for file_id in retained_ids]
    assert all(fetch["output_delete_results"])
    fetch["output_tags_after_delete"] = [
        live_run.probe("GET", f"/files/{file_id}/tags") for file_id in retained_ids
    ]
    assert all(result.get("status") == 403 for result in fetch["output_tags_after_delete"])
    # The fixture still cleans the inputs; outputs have already been explicitly
    # deleted here, exactly as the production fetch task does.
    live_run.output_ids.clear()
    live_run.save()
