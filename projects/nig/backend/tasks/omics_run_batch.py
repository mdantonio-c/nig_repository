"""Upload and submit one claimed Omics batch.

The dispatcher has already created the :class:`OmicsBatch` and moved every
selected dataset to ``QUEUED``. This task owns the irreversible remote work:
validating the locally stored FASTQs, uploading them and submitting one
``nig/germline`` task per dataset.

A submit response lost after the server accepted it is not safely retryable:
without an Omics idempotency key, retrying could launch the analysis twice.
Such a dataset is deliberately kept in ``SUBMIT_UNKNOWN`` for manual
reconciliation instead of being submitted again.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytz
from nig.endpoints import INPUT_ROOT
from nig.services.fastq import parse_fastq_filename
from nig.services.omics import OmicsClient, OmicsError, OmicsQuotaExceeded
from restapi.connectors import neo4j
from restapi.connectors.celery import CeleryExt, Task
from restapi.connectors.smtp.notifications import send_notification
from restapi.env import Env
from restapi.utilities.logs import log

READY_STATUS = "UPLOAD COMPLETED"
QUEUED_STATUS = "QUEUED"
RUNNING_STATUS = "RUNNING"
ERROR_STATUS = "ERROR"
SUBMITTING_STATUS = "SUBMITTING"
SUBMIT_UNKNOWN_STATUS = "SUBMIT_UNKNOWN"
OMICS_PIPELINE = "nig/germline"
OMICS_REFERENCE = "hg38"


class FastqValidationError(ValueError):
    """The persisted FASTQ metadata or input files cannot form one sample."""


def _dataset_input_path(dataset: Any) -> Path:
    owner = dataset.ownership.single()
    study = dataset.parent_study.single()
    if owner is None or study is None:
        raise FastqValidationError("Dataset has no owner or parent study")
    group = owner.belongs_to.single()
    if group is None:
        raise FastqValidationError("Dataset owner has no group")
    return INPUT_ROOT.joinpath(str(group.uuid), str(study.uuid), str(dataset.uuid))


def dataset_fastqs(dataset: Any) -> Tuple[str, List[Tuple[Any, Path]]]:
    """Validate and resolve exactly one single-end or paired-end FASTQ sample."""
    resolved: List[Tuple[str, str, Any, Path]] = []
    input_dir = _dataset_input_path(dataset)
    for file_node in dataset.files.all():
        parsed = parse_fastq_filename(file_node.name)
        if parsed is None:
            raise FastqValidationError(
                "Invalid FASTQ filename: expected SampleName_R1/R2.fastq.gz"
            )
        sample, read = parsed
        path = input_dir.joinpath(file_node.name)
        if not path.is_file():
            raise FastqValidationError(f"FASTQ file is missing: {file_node.name}")
        resolved.append((sample, read, file_node, path))

    if not resolved:
        raise FastqValidationError("Dataset has no FASTQ files")
    samples = {sample for sample, _, _, _ in resolved}
    reads = [read for _, read, _, _ in resolved]
    if (
        len(samples) != 1
        or len(resolved) not in (1, 2)
        or len(set(reads)) != len(reads)
    ):
        raise FastqValidationError("Dataset must contain one R1 or one R1/R2 pair")
    if "R1" not in reads:
        raise FastqValidationError("R1 file is missing")

    sample = resolved[0][0]
    ordered = sorted(resolved, key=lambda item: item[1])
    return sample, [(file_node, path) for _, _, file_node, path in ordered]


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(pytz.utc)


def _relation(dataset: Any, batch: Any) -> Any:
    return dataset.omics_batch.relationship(batch)


def _set_relation(
    dataset: Any,
    batch: Any,
    status: str,
    error: Optional[str] = None,
) -> None:
    relation = _relation(dataset, batch)
    relation.status = status
    if error is not None:
        relation.error_message = error
    relation.save()


def _notify_dataset_error(dataset: Any, error: str) -> None:
    study = dataset.parent_study.single()
    try:
        send_notification(
            subject="An Omics dataset analysis ended in an error",
            template="dataset_error.html",
            to_address=None,
            data={
                "dataset_id": dataset.uuid,
                "dataset_name": dataset.name,
                "study_id": study.uuid if study else "N/A",
                "study_name": study.name if study else "N/A",
                "error_message": error,
                "output_path": "N/A",
                "job_path": "N/A",
            },
        )
    except Exception as exc:  # notification must not undo persisted state
        log.error("Notification for Omics dataset {} failed: {}", dataset.uuid, exc)


def _mark_error(dataset: Any, batch: Any, error: str, now: datetime) -> None:
    dataset.status = ERROR_STATUS
    dataset.status_update = now
    dataset.error_message = error
    dataset.omics_status = ERROR_STATUS
    dataset.omics_status_update = now
    dataset.omics_error_message = error
    dataset.save()
    _set_relation(dataset, batch, ERROR_STATUS, error)
    _notify_dataset_error(dataset, error)


def _cleanup_uploaded(client: Any, uploaded: Iterable[Tuple[Any, str]]) -> None:
    for file_node, remote_id in uploaded:
        try:
            if client.delete_file(remote_id):
                file_node.omics_file_id = None
                file_node.omics_uploaded_at = None
                file_node.omics_status = None
                file_node.save()
        except Exception as exc:  # leave the id for the later orphan reconciler
            log.error("Cannot remove Omics upload for {}: {}", file_node.name, exc)


def _requeue_for_quota(dataset: Any, batch: Any, error: str, now: datetime) -> None:
    dataset.status = READY_STATUS
    dataset.status_update = now
    dataset.omics_status = None
    dataset.omics_status_update = now
    dataset.omics_error_message = error
    dataset.save()
    _set_relation(dataset, batch, READY_STATUS, error)


def _mark_submit_unknown(dataset: Any, batch: Any, error: str, now: datetime) -> None:
    """Fail closed after a submit error: the remote task might exist already."""
    dataset.status = QUEUED_STATUS
    dataset.status_update = now
    dataset.omics_status = SUBMIT_UNKNOWN_STATUS
    dataset.omics_status_update = now
    dataset.omics_error_message = error
    dataset.save()
    _set_relation(dataset, batch, SUBMIT_UNKNOWN_STATUS, error)
    _notify_dataset_error(dataset, error)


def _batch_uploaded_bytes(batch: Any) -> int:
    return int(batch.uploaded_bytes or 0)


def run_batch(
    graph: Any,
    client: Any,
    batch_uuid: str,
    dataset_uuids: Sequence[str],
    now: Optional[datetime] = None,
) -> Dict[str, List[str]]:
    """Execute one batch and return ids grouped by resulting disposition.

    The method is independent of Celery so it can be exhaustively tested with
    a mocked Omics client. It only processes datasets still claimed as QUEUED;
    therefore re-delivery of the same Celery message cannot submit a known
    task a second time.
    """
    timestamp = _now(now)
    batch = graph.OmicsBatch.nodes.get_or_none(uuid=batch_uuid)
    if batch is None:
        log.error("Omics batch {} does not exist", batch_uuid)
        return {"submitted": [], "failed": [], "requeued": [], "unknown": []}

    if batch.status not in ("PLANNED", RUNNING_STATUS):
        log.warning(
            "Omics batch {} is already terminal ({})", batch_uuid, batch.status
        )
        return {"submitted": [], "failed": [], "requeued": [], "unknown": []}

    batch.status = RUNNING_STATUS
    batch.save()
    report: Dict[str, List[str]] = {
        "submitted": [],
        "failed": [],
        "requeued": [],
        "unknown": [],
    }

    for index, dataset_uuid in enumerate(dataset_uuids):
        dataset = graph.Dataset.nodes.get_or_none(uuid=dataset_uuid)
        if dataset is None:
            log.warning(
                "Dataset {} is missing from Omics batch {}", dataset_uuid, batch_uuid
            )
            continue
        if dataset.omics_task_id:
            log.info("Dataset {} already has an Omics task, skipping", dataset_uuid)
            continue
        if dataset.status != QUEUED_STATUS or dataset.omics_status != QUEUED_STATUS:
            log.warning(
                "Dataset {} is no longer queued for this batch, skipping", dataset_uuid
            )
            continue

        uploaded: List[Tuple[Any, str]] = []
        try:
            sample, fastqs = dataset_fastqs(dataset)
            for file_node, path in fastqs:
                file_node.omics_status = "UPLOADING"
                file_node.save()
                remote_id = client.upload_file(path, tags=["nig", str(dataset.uuid)])
                file_node.omics_file_id = remote_id
                file_node.omics_uploaded_at = timestamp
                file_node.omics_status = "UPLOADED"
                file_node.save()
                uploaded.append((file_node, remote_id))

            input_ids = [remote_id for _, remote_id in uploaded]
            batch.uploaded_bytes = _batch_uploaded_bytes(batch) + sum(
                int(file_node.size or 0) for file_node, _ in uploaded
            )
            batch.save()

            # Persist this state before submit. A request timeout after this
            # point is never automatically re-submitted (T4 protection).
            dataset.omics_status = SUBMITTING_STATUS
            dataset.omics_status_update = timestamp
            dataset.save()
            response = client.submit_nig_germline(
                input_ids,
                output_vcf=f"{sample}_{dataset.uuid}.g.vcf.gz",
                reference=Env.get("OMICS_REFERENCE_VERSION", OMICS_REFERENCE),
            )
            task_id = response.get("task_id")
            if not task_id:
                raise OmicsError("Omics submit response has no task_id")

            dataset.status = RUNNING_STATUS
            dataset.status_update = timestamp
            dataset.error_message = None
            dataset.omics_task_id = str(task_id)
            dataset.omics_pipeline = OMICS_PIPELINE
            dataset.omics_status = RUNNING_STATUS
            dataset.omics_submitted_at = timestamp
            dataset.omics_status_update = timestamp
            dataset.omics_error_message = None
            dataset.save()
            _set_relation(dataset, batch, RUNNING_STATUS)
            report["submitted"].append(str(dataset.uuid))
        except OmicsQuotaExceeded as exc:
            message = f"Omics quota exceeded during upload: {exc}"
            _cleanup_uploaded(client, uploaded)
            _requeue_for_quota(dataset, batch, message, timestamp)
            report["requeued"].append(str(dataset.uuid))

            # Do not try later queued datasets: remote usage has proven the
            # plan stale. Return their claims to the dispatcher as well.
            for pending_uuid in dataset_uuids[index + 1 :]:
                pending = graph.Dataset.nodes.get_or_none(uuid=pending_uuid)
                if (
                    pending is not None
                    and pending.status == QUEUED_STATUS
                    and pending.omics_status == QUEUED_STATUS
                ):
                    _requeue_for_quota(pending, batch, message, timestamp)
                    report["requeued"].append(str(pending.uuid))
            batch.planned_bytes = _batch_uploaded_bytes(batch)
            batch.status = RUNNING_STATUS if report["submitted"] else ERROR_STATUS
            batch.save()
            break
        except FastqValidationError as exc:
            _mark_error(dataset, batch, str(exc), timestamp)
            report["failed"].append(str(dataset.uuid))
        except OmicsError as exc:
            # If upload failed, successful file uploads for this dataset are
            # removable. If submit failed after SUBMITTING, retain them and
            # fail closed because Omics may already have accepted the submit.
            if dataset.omics_status == SUBMITTING_STATUS:
                _mark_submit_unknown(dataset, batch, str(exc), timestamp)
                report["unknown"].append(str(dataset.uuid))
            else:
                _cleanup_uploaded(client, uploaded)
                _mark_error(dataset, batch, str(exc), timestamp)
                report["failed"].append(str(dataset.uuid))
        except Exception as exc:
            message = f"Unexpected Omics error: {exc}"
            if dataset.omics_status == SUBMITTING_STATUS:
                _mark_submit_unknown(dataset, batch, message, timestamp)
                report["unknown"].append(str(dataset.uuid))
            else:
                _cleanup_uploaded(client, uploaded)
                _mark_error(dataset, batch, message, timestamp)
                report["failed"].append(str(dataset.uuid))

    if not report["submitted"] and not report["unknown"] and not report["requeued"]:
        batch.status = ERROR_STATUS
        batch.save()
    return report


def _client_from_env() -> OmicsClient:
    return OmicsClient(
        Env.get("OMICS_API_URL", ""),
        Env.get("OMICS_USERNAME", ""),
        Env.get("OMICS_PASSWORD", ""),
        timeout=Env.get_int("OMICS_REQUEST_TIMEOUT", 60),
    )


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def omics_run_batch(
    self: Task[[str, List[str]], None], batch_uuid: str, dataset_uuids: List[str]
) -> None:
    log.info("Start Omics batch {} in Celery task {}", batch_uuid, self.request.id)
    run_batch(neo4j.get_instance(), _client_from_env(), batch_uuid, dataset_uuids)
