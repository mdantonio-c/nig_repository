"""Retrieve, validate and persist the retained outputs of an Omics task."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
from nig.endpoints import OUTPUT_ROOT
from nig.services.omics import OmicsClient, OmicsError
from restapi.connectors import neo4j
from restapi.connectors.celery import CeleryExt, Task
from restapi.env import Env
from restapi.utilities.logs import log

FETCHING = "FETCHING"
CLEANUP_PENDING = "CLEANUP PENDING"
COMPLETED = "COMPLETED"
ERROR = "ERROR"
RETAINED_KINDS = {"gvcf": "GVCF", "tbi": "TBI", "bam": "BAM"}
REQUIRED_KINDS = {"GVCF", "TBI", "BAM"}


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(pytz.utc)


def _client_from_env() -> OmicsClient:
    return OmicsClient(
        Env.get("OMICS_API_URL", ""),
        Env.get("OMICS_USERNAME", ""),
        Env.get("OMICS_PASSWORD", ""),
        timeout=Env.get_int("OMICS_REQUEST_TIMEOUT", 60),
    )


def _output_dir(dataset: Any) -> Path:
    owner = dataset.ownership.single()
    study = dataset.parent_study.single()
    if owner is None or study is None or owner.belongs_to.single() is None:
        raise OmicsError("Dataset has no owner, group or parent study")
    group = owner.belongs_to.single()
    # The explicit Omics subdirectory prevents collisions with the established
    # local Snakemake paths until joint analysis becomes backend-agnostic.
    return OUTPUT_ROOT.joinpath(str(group.uuid), str(study.uuid), str(dataset.uuid), "omics")


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
    artifact.kind = RETAINED_KINDS[str(output["_kind"]).lower()]
    artifact.status = "DISCOVERED"
    artifact.save()
    return artifact


def _expected_outputs(outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected = [
        output
        for output in outputs
        if str(output.get("_kind", "")).lower() in RETAINED_KINDS
    ]
    kinds = {RETAINED_KINDS[str(output["_kind"]).lower()] for output in selected}
    if kinds != REQUIRED_KINDS:
        raise OmicsError(
            "Omics task outputs must include exactly gVCF, TBI and BAM; "
            f"received {sorted(kinds)}"
        )
    for output in selected:
        if not output.get("file_id") or not output.get("user_filename"):
            raise OmicsError("Omics output is missing file_id or user_filename")
        if int(output.get("size", 0)) <= 0:
            raise OmicsError("Omics output has an invalid size")
    return selected


def _cleanup_observed(client: Any, remote_ids: List[str]) -> bool:
    """Return true only when completed download outputs no longer appear remotely."""
    remote = client.list_uploaded_files()
    listed = {str(item.get("file_id")) for item in remote if isinstance(item, dict)}
    return not any(remote_id in listed for remote_id in remote_ids)


def _batch_status(dataset: Any) -> None:
    for batch in dataset.omics_batch.all():
        members = batch.datasets.all()
        statuses = {member.status for member in members}
        if statuses and statuses <= {COMPLETED}:
            batch.status = COMPLETED
        elif ERROR in statuses and statuses <= {COMPLETED, ERROR}:
            batch.status = ERROR
        else:
            continue
        batch.save()


def fetch_results(
    graph: Any,
    client: Any,
    dataset_uuid: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    timestamp = _now(now)
    dataset = graph.Dataset.nodes.get_or_none(uuid=dataset_uuid)
    if dataset is None or dataset.omics_status != FETCHING:
        return {"downloaded": [], "skipped": True}

    try:
        outputs = _expected_outputs(client.get_task_files(dataset.omics_task_id))
        destination = _output_dir(dataset)
        destination.mkdir(parents=True, exist_ok=True)
        artifacts = [_artifact(graph, dataset, output) for output in outputs]
        for artifact in artifacts:
            artifact.status = "DOWNLOADING"
            artifact.save()
            target = destination.joinpath(artifact.name)
            client.download_file(
                artifact.remote_file_id, target, expected_size=artifact.size
            )
            os.chmod(target, 0o440)
            artifact.local_path = str(target)
            artifact.downloaded_at = timestamp
            artifact.status = "DOWNLOADED"
            artifact.save()

        remote_ids = [artifact.remote_file_id for artifact in artifacts]
        if not _cleanup_observed(client, remote_ids):
            dataset.omics_status = CLEANUP_PENDING
            dataset.omics_error_message = "Output cleanup not yet observed on Omics"
            dataset.omics_status_update = timestamp
            dataset.save()
            return {"downloaded": remote_ids, "cleanup_pending": True}

        dataset.status = COMPLETED
        dataset.status_update = timestamp
        dataset.error_message = None
        dataset.omics_status = COMPLETED
        dataset.omics_status_update = timestamp
        dataset.omics_error_message = None
        dataset.save()
        _batch_status(dataset)
        return {"downloaded": remote_ids, "cleanup_pending": False}
    except Exception as exc:
        message = f"Omics result retrieval failed: {exc}"
        log.error("Dataset {}: {}", dataset_uuid, message)
        dataset.omics_error_message = message
        dataset.omics_status_update = timestamp
        dataset.save()
        return {"downloaded": [], "error": message}


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def omics_fetch_results(self: Task[[str], None], dataset_uuid: str) -> None:
    fetch_results(neo4j.get_instance(), _client_from_env(), dataset_uuid)
