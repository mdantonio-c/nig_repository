"""Retrieve, validate and persist the retained outputs of an Omics task.

Idempotent and resumable: Omics deletes an output after its first complete
download, so artifacts already downloaded and present locally are never
requested again; a retry only fetches what is still missing. The poller
re-dispatches this task for ``FETCHING`` (failed/lost fetch) and
``CLEANUP PENDING`` (remote cleanup not yet observed) datasets.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
from nig.endpoints import OUTPUT_ROOT
from nig.services.omics import OmicsError
from nig.services.omics.batch_state import set_relation_status
from nig.services.omics.settings import client_from_env, omics_enabled
from restapi.connectors import neo4j
from restapi.connectors.celery import CeleryExt, Task
from restapi.utilities.logs import log

FETCHING = "FETCHING"
CLEANUP_PENDING = "CLEANUP PENDING"
COMPLETED = "COMPLETED"
ERROR = "ERROR"
DOWNLOADED = "DOWNLOADED"
# Omics exposes the graph class name in ``_kind`` (``Vcf``/``Bam``, covering
# both an artifact and its index) with no separate index flag in the API
# response; the ``extension`` suffix is the only way to tell them apart.
RETAINED_RAW_KINDS = {"vcf", "bam"}
REQUIRED_KINDS = {"GVCF", "TBI", "BAM", "BAI"}
ALLOWED_SUFFIXES = {
    "GVCF": ".g.vcf.gz",
    "TBI": ".g.vcf.gz.tbi",
    "BAM": ".bam",
    "BAI": ".bam.bai",
}


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(pytz.utc)


def _output_dir(dataset: Any) -> Path:
    owner = dataset.ownership.single()
    study = dataset.parent_study.single()
    if owner is None or study is None or owner.belongs_to.single() is None:
        raise OmicsError("Dataset has no owner, group or parent study")
    group = owner.belongs_to.single()
    # The explicit Omics subdirectory prevents collisions with the established
    # local Snakemake paths until joint analysis becomes backend-agnostic.
    return OUTPUT_ROOT.joinpath(str(group.uuid), str(study.uuid), str(dataset.uuid), "omics")


def _kind(output: Dict[str, Any]) -> str:
    raw = str(output.get("_kind", "")).lower()
    extension = str(output.get("extension", "")).lower()
    if raw == "vcf":
        return "TBI" if extension.endswith("tbi") else "GVCF"
    if raw == "bam":
        return "BAI" if extension.endswith("bai") else "BAM"
    raise KeyError(raw)


def _artifact(graph: Any, dataset: Any, output: Dict[str, Any]) -> Any:
    remote_id = str(output["file_id"])
    artifact = graph.OmicsArtifact.nodes.get_or_none(remote_file_id=remote_id)
    if artifact is None:
        artifact = graph.OmicsArtifact(
            remote_file_id=remote_id,
            name=str(output["user_filename"]),
        ).save()
        artifact.dataset.connect(dataset)
    artifact.extension = output.get("extension")
    artifact.size = int(output["size"])
    artifact.kind = _kind(output)
    artifact.status = "DISCOVERED"
    artifact.save()
    return artifact


def _downloaded_artifacts(dataset: Any) -> Dict[str, Any]:
    """Artifacts already verified and still present on the local filesystem."""
    found: Dict[str, Any] = {}
    for artifact in dataset.omics_artifacts.all():
        if (
            artifact.status == DOWNLOADED
            and artifact.local_path
            and Path(artifact.local_path).is_file()
        ):
            found[artifact.kind] = artifact
    return found


def _expected_outputs(
    outputs: List[Dict[str, Any]],
    already: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Validate the retained outputs, returning only those still to download.

    ``already`` maps the kinds downloaded by a previous attempt to their
    filename: Omics may no longer list them, and they are not requested again.
    """
    already = already or {}
    selected = [
        output
        for output in outputs
        if str(output.get("_kind", "")).lower() in RETAINED_RAW_KINDS
    ]
    kinds = [_kind(output) for output in selected]
    remaining = [output for output in selected if _kind(output) not in already]
    remaining_kinds = [_kind(output) for output in remaining]
    if (
        len(kinds) != len(set(kinds))
        or len(remaining_kinds) != len(set(remaining_kinds))
        or set(remaining_kinds) | set(already) != REQUIRED_KINDS
    ):
        raise OmicsError(
            "Omics task outputs must include exactly gVCF, TBI, BAM and BAI; "
            f"received {sorted(kinds)}, already downloaded {sorted(already)}"
        )
    names = dict(already)
    for output in remaining:
        if not output.get("file_id") or not output.get("user_filename"):
            raise OmicsError("Omics output is missing file_id or user_filename")
        if int(output.get("size", 0)) <= 0:
            raise OmicsError("Omics output has an invalid size")
        kind = _kind(output)
        filename = str(output["user_filename"])
        if Path(filename).name != filename or not filename.endswith(ALLOWED_SUFFIXES[kind]):
            raise OmicsError(f"Unexpected Omics {kind} output filename")
        names[kind] = filename
    if names["TBI"] != f"{names['GVCF']}.tbi":
        raise OmicsError("Omics TBI output does not match the gVCF output")
    if names["BAI"] != f"{names['BAM']}.bai":
        raise OmicsError("Omics BAI output does not match the BAM output")
    return remaining


def _cleanup_observed(client: Any, remote_names: List[str]) -> bool:
    """Return true only when completed download outputs no longer appear remotely.

    Omics re-encrypts every ``file_id`` on each response, so a previously
    saved id can never be found again in a fresh listing: ``user_filename``
    is the only stable, NIG-owned key (dataset-uuid-prefixed, so unique).
    """
    remote = client.list_uploaded_files()
    listed = {str(item.get("user_filename")) for item in remote if isinstance(item, dict)}
    return not any(name in listed for name in remote_names)


def _complete_or_wait_cleanup(
    dataset: Any, client: Any, remote_names: List[str], timestamp: datetime
) -> bool:
    """Close the dataset if the remote cleanup is observed; else CLEANUP PENDING."""
    if not _cleanup_observed(client, remote_names):
        dataset.status = "RUNNING"
        dataset.omics_status = CLEANUP_PENDING
        dataset.omics_error_message = "Output cleanup not yet observed on Omics"
        dataset.omics_status_update = timestamp
        dataset.save()
        set_relation_status(dataset, CLEANUP_PENDING)
        return False

    dataset.status = COMPLETED
    dataset.status_update = timestamp
    dataset.error_message = None
    dataset.omics_status = COMPLETED
    dataset.omics_status_update = timestamp
    dataset.omics_error_message = None
    dataset.save()
    set_relation_status(dataset, COMPLETED)
    return True


def fetch_results(
    graph: Any,
    client: Any,
    dataset_uuid: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    timestamp = _now(now)
    dataset = graph.Dataset.nodes.get_or_none(uuid=dataset_uuid)
    if dataset is None or dataset.omics_status not in (FETCHING, CLEANUP_PENDING):
        return {"downloaded": [], "skipped": True}

    current: Optional[Any] = None
    try:
        already = _downloaded_artifacts(dataset)
        if dataset.omics_status == CLEANUP_PENDING:
            if set(already) == REQUIRED_KINDS:
                remote_names = [str(a.name) for a in already.values()]
                completed = _complete_or_wait_cleanup(
                    dataset, client, remote_names, timestamp
                )
                return {"downloaded": [], "cleanup_pending": not completed}
            # Local outputs lost after download: retrieve them again.
            dataset.omics_status = FETCHING
            dataset.omics_status_update = timestamp
            dataset.save()
            set_relation_status(dataset, FETCHING)

        outputs = _expected_outputs(
            client.get_task_files(dataset.omics_task_id),
            {kind: artifact.name for kind, artifact in already.items()},
        )
        destination = _output_dir(dataset)
        destination.mkdir(parents=True, exist_ok=True)
        artifacts = [_artifact(graph, dataset, output) for output in outputs]
        client.ensure_free_space(
            destination, sum(int(artifact.size) for artifact in artifacts)
        )
        downloaded: List[str] = []
        for artifact in artifacts:
            current = artifact
            artifact.status = "DOWNLOADING"
            artifact.save()
            target = destination.joinpath(artifact.name)
            client.download_file(
                artifact.remote_file_id, target, expected_size=artifact.size
            )
            os.chmod(target, 0o440)
            artifact.local_path = str(target)
            artifact.downloaded_at = timestamp
            artifact.status = DOWNLOADED
            artifact.save()
            downloaded.append(str(artifact.remote_file_id))
        current = None

        remote_names = [str(a.name) for a in already.values()] + [
            str(artifact.name) for artifact in artifacts
        ]
        completed = _complete_or_wait_cleanup(dataset, client, remote_names, timestamp)
        return {"downloaded": downloaded, "cleanup_pending": not completed}
    except Exception as exc:
        # Technical detail only: the dataset stays FETCHING (user sees
        # RUNNING) and the poller retries after the back-off.
        message = f"Omics result retrieval failed: {exc}"
        log.error("Dataset {}: {}", dataset_uuid, message)
        if current is not None:
            current.status = ERROR
            current.save()
        dataset.omics_error_message = message
        dataset.omics_status_update = timestamp
        dataset.save()
        return {"downloaded": [], "error": message}


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def omics_fetch_results(self: Task[[str], None], dataset_uuid: str) -> None:
    if not omics_enabled():
        log.warning("OMICS_ENABLE is off, Omics fetch for {} not executed", dataset_uuid)
        return
    fetch_results(neo4j.get_instance(), client_from_env(), dataset_uuid)
