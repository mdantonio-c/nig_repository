"""Upload and submit one claimed Omics batch.

The dispatcher has already created the :class:`OmicsBatch` and moved every
selected dataset to ``QUEUED``. This task owns the irreversible remote work:
validating the locally stored FASTQs, uploading them and submitting one
``nig/germline`` task per dataset.

A submit response lost after the server accepted it is not safely retryable:
without an Omics idempotency key, retrying could launch the analysis twice.
Such a dataset, like one whose accepted submit could not be saved locally, is
deliberately kept in ``SUBMIT_UNKNOWN`` for manual reconciliation instead of
being submitted again or cleaned up.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytz
from nig.endpoints import INPUT_ROOT
from nig.services.fastq import parse_fastq_filename
from nig.services.omics import OmicsError, OmicsQuotaExceeded
from nig.services.omics.batch_state import finalize_batch
from nig.services.omics.client import _obscure
from nig.services.omics.settings import (
    USER_ANALYSIS_ERROR,
    client_from_env,
    omics_enabled,
)
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


def _mark_error(
    dataset: Any, batch: Any, user_message: str, detail: str, now: datetime
) -> None:
    """``user_message`` is shown to NIG users; ``detail`` stays technical."""
    dataset.status = ERROR_STATUS
    dataset.status_update = now
    dataset.error_message = user_message
    dataset.omics_status = ERROR_STATUS
    dataset.omics_status_update = now
    dataset.omics_error_message = detail
    dataset.save()
    _set_relation(dataset, batch, ERROR_STATUS, detail)
    _notify_dataset_error(dataset, detail)


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


def remote_filename(dataset: Any, path: Path) -> str:
    """Remote name unique per dataset: Omics resumes uploads by filename."""
    return f"{dataset.uuid}_{path.name}"


def _skip_not_queued(dataset: Any, batch: Any, now: datetime) -> Optional[str]:
    """Handle a dataset of this batch found in an unexpected state.

    Returns the report key to record it under, if any.
    """
    if dataset.omics_status == SUBMITTING_STATUS:
        # A previous delivery crashed after persisting SUBMITTING: the remote
        # task may exist. Fail closed exactly like a lost submit response.
        _mark_submit_unknown(
            dataset,
            batch,
            "Submit interrupted before a response was recorded",
            now,
        )
        return "unknown"
    relation = _relation(dataset, batch)
    if relation is not None and relation.status == QUEUED_STATUS:
        # Changed outside this task: close the claim so the batch can finish.
        relation.status = ERROR_STATUS
        relation.error_message = "Dataset no longer queued for this batch"
        relation.save()
    return None


def _hold_after_submit(
    dataset: Any, batch: Any, detail: str, task_id: Optional[str], now: datetime
) -> None:
    """Any error once submit was attempted: fail closed, never clean up.

    The remote analysis may exist (and certainly does with a ``task_id``): the
    inputs are kept and the known task id is recorded for reconciliation.
    """
    if task_id:
        dataset.omics_task_id = task_id
        detail = f"Omics accepted the task but its state was not saved: {detail}"
    try:
        _mark_submit_unknown(dataset, batch, detail, now)
    except Exception as exc:
        # The graph still holds SUBMITTING: a redelivery fails closed as well.
        log.error(
            "Cannot record the uncertain submit of dataset {} (Omics task {}): {}",
            dataset.uuid,
            _obscure(task_id) if task_id else "unknown",
            exc,
        )


def _run_dataset(
    graph: Any,
    client: Any,
    batch: Any,
    dataset: Any,
    pending_uuids: Sequence[str],
    report: Dict[str, List[str]],
    timestamp: datetime,
) -> bool:
    """Upload and submit one dataset; return True when the batch must stop."""
    uploaded: List[Tuple[Any, str]] = []
    submit_attempted = False
    task_id: Optional[str] = None
    try:
        sample, fastqs = dataset_fastqs(dataset)
        new_bytes = 0
        for file_node, path in fastqs:
            if file_node.omics_file_id and file_node.omics_status == "UPLOADED":
                # Redelivered message: reuse the tracked upload instead of
                # overwriting (and orphaning) the registered remote id.
                uploaded.append((file_node, str(file_node.omics_file_id)))
                continue
            file_node.omics_status = "UPLOADING"
            file_node.save()
            remote_id = client.upload_file(
                path,
                tags=["nig", str(dataset.uuid)],
                remote_filename=remote_filename(dataset, path),
            )
            file_node.omics_file_id = remote_id
            file_node.omics_uploaded_at = timestamp
            file_node.omics_status = "UPLOADED"
            file_node.save()
            uploaded.append((file_node, remote_id))
            new_bytes += int(file_node.size or 0)

        input_ids = [remote_id for _, remote_id in uploaded]
        batch.uploaded_bytes = _batch_uploaded_bytes(batch) + new_bytes
        batch.save()

        # Persist this state before submit. A request timeout after this
        # point is never automatically re-submitted (T4 protection).
        output_vcf = f"{sample}_{dataset.uuid}.g.vcf.gz"
        dataset.omics_status = SUBMITTING_STATUS
        dataset.omics_status_update = timestamp
        dataset.omics_output_prefix = output_vcf
        dataset.save()
        submit_attempted = True
        response = client.submit_nig_germline(
            input_ids,
            output_vcf=output_vcf,
            reference=Env.get("OMICS_REFERENCE_VERSION", OMICS_REFERENCE),
        )
        task_id = str(response.get("task_id") or "") or None
        if not task_id:
            raise OmicsError("Omics submit response has no task_id")

        dataset.status = RUNNING_STATUS
        dataset.status_update = timestamp
        dataset.error_message = None
        dataset.omics_task_id = task_id
        dataset.omics_pipeline = OMICS_PIPELINE
        dataset.omics_status = RUNNING_STATUS
        dataset.omics_submitted_at = timestamp
        dataset.omics_status_update = timestamp
        dataset.omics_error_message = None
        dataset.save()
        _set_relation(dataset, batch, RUNNING_STATUS)
        report["submitted"].append(str(dataset.uuid))
    except OmicsQuotaExceeded as exc:
        # An explicit refusal: nothing was accepted remotely, even at submit.
        message = f"Omics quota exceeded during upload: {exc}"
        _cleanup_uploaded(client, uploaded)
        _requeue_for_quota(dataset, batch, message, timestamp)
        report["requeued"].append(str(dataset.uuid))

        # Do not try later queued datasets: remote usage has proven the
        # plan stale. Return their claims to the dispatcher as well.
        for pending_uuid in pending_uuids:
            pending = graph.Dataset.nodes.get_or_none(uuid=pending_uuid)
            if (
                pending is not None
                and pending.status == QUEUED_STATUS
                and pending.omics_status == QUEUED_STATUS
            ):
                _requeue_for_quota(pending, batch, message, timestamp)
                report["requeued"].append(str(pending.uuid))
        batch.planned_bytes = _batch_uploaded_bytes(batch)
        batch.save()
        return True
    except FastqValidationError as exc:
        # Validation messages only describe the user's own FASTQ names.
        _mark_error(dataset, batch, str(exc), str(exc), timestamp)
        report["failed"].append(str(dataset.uuid))
    except Exception as exc:
        prefix = "" if isinstance(exc, OmicsError) else "Unexpected error: "
        detail = f"{prefix}{exc}"
        if submit_attempted:
            # Covers a lost response and a local failure after an accepted
            # submit: Omics may run the analysis, keep inputs and hold.
            _hold_after_submit(dataset, batch, detail, task_id, timestamp)
            report["unknown"].append(str(dataset.uuid))
        else:
            # Nothing submitted: this dataset's uploads are removable.
            _cleanup_uploaded(client, uploaded)
            _mark_error(dataset, batch, USER_ANALYSIS_ERROR, detail, timestamp)
            report["failed"].append(str(dataset.uuid))
    return False


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
    report: Dict[str, List[str]] = {
        "submitted": [],
        "failed": [],
        "requeued": [],
        "unknown": [],
        "missing": [],
    }
    batch = graph.OmicsBatch.nodes.get_or_none(uuid=batch_uuid)
    if batch is None:
        log.error("Omics batch {} does not exist", batch_uuid)
        return report

    if batch.status not in ("PLANNED", RUNNING_STATUS):
        log.warning(
            "Omics batch {} is already terminal ({})", batch_uuid, batch.status
        )
        return report

    batch.status = RUNNING_STATUS
    batch.save()

    for index, dataset_uuid in enumerate(dataset_uuids):
        dataset = graph.Dataset.nodes.get_or_none(uuid=dataset_uuid)
        if dataset is None:
            # Deleted: its relationship is gone too, finalize_batch ignores it.
            log.warning(
                "Dataset {} is missing from Omics batch {}", dataset_uuid, batch_uuid
            )
            report["missing"].append(str(dataset_uuid))
            continue
        if dataset.omics_task_id:
            log.info("Dataset {} already has an Omics task, skipping", dataset_uuid)
            continue
        if dataset.status != QUEUED_STATUS or dataset.omics_status != QUEUED_STATUS:
            log.warning(
                "Dataset {} is no longer queued for this batch, skipping", dataset_uuid
            )
            key = _skip_not_queued(dataset, batch, timestamp)
            if key:
                report[key].append(str(dataset.uuid))
            continue

        try:
            stop = _run_dataset(
                graph,
                client,
                batch,
                dataset,
                dataset_uuids[index + 1 :],
                report,
                timestamp,
            )
        except Exception as exc:
            # Recording the outcome failed (e.g. graph unavailable): whatever
            # is persisted stays fail-closed; never stop the other datasets.
            log.error(
                "Cannot record the Omics outcome of dataset {} in batch {}: {}",
                dataset_uuid,
                batch_uuid,
                exc,
            )
            continue
        if stop:
            break

    finalize_batch(batch)
    return report


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def omics_run_batch(
    self: Task[[str, List[str]], None], batch_uuid: str, dataset_uuids: List[str]
) -> None:
    if not omics_enabled():
        log.warning("OMICS_ENABLE is off, Omics batch {} not executed", batch_uuid)
        return
    log.info("Start Omics batch {} in Celery task {}", batch_uuid, self.request.id)
    run_batch(neo4j.get_instance(), client_from_env(), batch_uuid, dataset_uuids)
