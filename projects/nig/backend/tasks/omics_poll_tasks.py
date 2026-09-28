"""Poll submitted Omics analyses and dispatch result retrieval.

Also the recovery loop for retrieval: datasets left in ``FETCHING`` (lost or
failed fetch message) or ``CLEANUP PENDING`` (remote cleanup not yet observed)
are re-dispatched with a back-off, until ``OMICS_FETCH_MAX_ATTEMPTS``.
"""

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import pytz
from nig.services.omics.batch_state import set_relation_status
from nig.services.omics.client import _obscure
from nig.services.omics.settings import (
    USER_ANALYSIS_ERROR,
    client_from_env,
    omics_enabled,
)
from restapi.connectors import celery, neo4j
from restapi.connectors.celery import CeleryExt, Task
from restapi.connectors.smtp.notifications import send_notification
from restapi.env import Env
from restapi.utilities.logs import log

SUBMITTED = "SUBMITTED"
RUNNING = "RUNNING"
FETCHING = "FETCHING"
CLEANUP_PENDING = "CLEANUP PENDING"
ERROR = "ERROR"
FETCH_TASK = "omics_fetch_results"
POLLABLE = (SUBMITTED, RUNNING)
RETRIEVING = (FETCHING, CLEANUP_PENDING)
DEFAULT_FETCH_RETRY_MINUTES = 60
DEFAULT_FETCH_MAX_ATTEMPTS = 5


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(pytz.utc)


def _notify_error(dataset: Any, message: str) -> None:
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
                "error_message": message,
                "output_path": "N/A",
                "job_path": "N/A",
            },
        )
    except Exception as exc:  # pragma: no cover - SMTP is best effort
        log.error("Notification for Omics dataset {} failed: {}", dataset.uuid, exc)


def mark_error(dataset: Any, detail: str, now: datetime) -> None:
    """Terminal failure: generic user message, technical detail kept aside."""
    dataset.status = ERROR
    dataset.status_update = now
    dataset.error_message = USER_ANALYSIS_ERROR
    dataset.omics_status = ERROR
    dataset.omics_status_update = now
    dataset.omics_error_message = detail
    dataset.save()
    set_relation_status(dataset, ERROR, detail)
    _notify_error(dataset, detail)


def send_fetch(dataset_uuid: str) -> str:
    task = celery.get_instance().celery_app.send_task(
        FETCH_TASK, args=(dataset_uuid,), countdown=1
    )
    return str(task.id)


def _fetch_due(dataset: Any, now: datetime, retry_minutes: int) -> bool:
    last = dataset.omics_status_update
    return last is None or last <= now - timedelta(minutes=retry_minutes)


def _dispatch_fetch(
    dataset: Any, send_task: Callable[[str], str], now: datetime
) -> bool:
    """Persist FETCHING first, then enqueue: the fetch never sees a stale state.

    If the broker refuses the message the dataset simply stays FETCHING and
    the retrieval recovery loop sends it again after the back-off.
    A ``CLEANUP PENDING`` re-check keeps its state and consumes no attempt:
    its outputs are already local.
    """
    dataset.omics_status_update = now
    if dataset.omics_status != CLEANUP_PENDING:
        dataset.status = RUNNING
        dataset.status_update = now
        dataset.omics_status = FETCHING
        dataset.omics_fetch_attempts = int(dataset.omics_fetch_attempts or 0) + 1
    dataset.save()
    if dataset.omics_status == FETCHING:
        set_relation_status(dataset, FETCHING)
    try:
        send_task(str(dataset.uuid))
    except Exception as exc:
        log.error("Cannot enqueue fetch for Omics dataset {}: {}", dataset.uuid, exc)
        return False
    return True


def _poll_one(
    dataset: Any,
    client: Any,
    send_task: Callable[[str], str],
    now: datetime,
    retry_minutes: int,
    max_attempts: int,
) -> Optional[str]:
    """Synchronize one dataset; return the report key, if any."""
    if dataset.omics_status in RETRIEVING:
        if not _fetch_due(dataset, now, retry_minutes):
            return None
        # Outputs are already local in CLEANUP PENDING: keep re-checking the
        # remote cleanup without a limit (the still active batch triggers the
        # stale-batch alert). Only failed downloads consume attempts.
        if (
            dataset.omics_status == FETCHING
            and int(dataset.omics_fetch_attempts or 0) >= max_attempts
        ):
            mark_error(
                dataset,
                f"Result retrieval abandoned after {max_attempts} attempts: "
                f"{dataset.omics_error_message or 'no detail'}",
                now,
            )
            return "failed"
        return "fetching" if _dispatch_fetch(dataset, send_task, now) else None

    if dataset.omics_status not in POLLABLE:
        return None

    remote = client.get_task(dataset.omics_task_id)
    status = remote.status.lower()
    if status in ("pending", "received"):
        local_status = SUBMITTED
    elif status == "processing":
        local_status = RUNNING
    elif status == "complete":
        dataset.omics_fetch_attempts = 0
        return "fetching" if _dispatch_fetch(dataset, send_task, now) else None
    elif status == "error":
        mark_error(dataset, "Remote task reported Error", now)
        return "failed"
    else:
        log.warning("Unknown Omics task status '{}' for {}", remote.status, dataset.uuid)
        return None

    dataset.status = RUNNING
    dataset.status_update = now
    dataset.omics_status = local_status
    dataset.omics_status_update = now
    dataset.save()
    set_relation_status(dataset, local_status)
    return local_status.lower()


def poll_tasks(
    graph: Any,
    client: Any,
    send_task: Callable[[str], str] = send_fetch,
    now: Optional[datetime] = None,
    retry_minutes: int = DEFAULT_FETCH_RETRY_MINUTES,
    max_attempts: int = DEFAULT_FETCH_MAX_ATTEMPTS,
) -> Dict[str, List[str]]:
    """Synchronize active NIG datasets with their authoritative Omics status.

    Each dataset is isolated: a remote/graph error on one of them is logged
    and reported, and never stops the others from being polled.
    """
    timestamp = _now(now)
    report: Dict[str, List[str]] = {
        "submitted": [],
        "running": [],
        "fetching": [],
        "failed": [],
        "poll_errors": [],
    }
    datasets = graph.Dataset.nodes.filter(omics_task_id__isnull=False).all()
    for dataset in datasets:
        try:
            key = _poll_one(
                dataset, client, send_task, timestamp, retry_minutes, max_attempts
            )
        except Exception as exc:
            log.error(
                "Cannot poll Omics task {} of dataset {}: {}",
                _obscure(str(dataset.omics_task_id)),
                dataset.uuid,
                exc,
            )
            report["poll_errors"].append(str(dataset.uuid))
            continue
        if key:
            report[key].append(str(dataset.uuid))
    return report


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def omics_poll_tasks(self: Task[[], None]) -> None:
    if not omics_enabled():
        log.warning("OMICS_ENABLE is off, Omics poll not executed")
        return
    report = poll_tasks(
        neo4j.get_instance(),
        client_from_env(),
        retry_minutes=Env.get_int(
            "OMICS_FETCH_RETRY_MINUTES", DEFAULT_FETCH_RETRY_MINUTES
        ),
        max_attempts=Env.get_int("OMICS_FETCH_MAX_ATTEMPTS", DEFAULT_FETCH_MAX_ATTEMPTS),
    )
    log.info(
        "Omics poll completed: {}", {key: len(value) for key, value in report.items()}
    )
