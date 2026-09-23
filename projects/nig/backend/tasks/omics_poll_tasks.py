"""Poll submitted Omics analyses and dispatch result retrieval."""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import pytz
from nig.services.omics import OmicsClient
from restapi.connectors import celery, neo4j
from restapi.connectors.celery import CeleryExt, Task
from restapi.connectors.smtp.notifications import send_notification
from restapi.env import Env
from restapi.utilities.logs import log

SUBMITTED = "SUBMITTED"
RUNNING = "RUNNING"
FETCHING = "FETCHING"
ERROR = "ERROR"
FETCH_TASK = "omics_fetch_results"
POLLABLE = (SUBMITTED, RUNNING)


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(pytz.utc)


def _client_from_env() -> OmicsClient:
    return OmicsClient(
        Env.get("OMICS_API_URL", ""),
        Env.get("OMICS_USERNAME", ""),
        Env.get("OMICS_PASSWORD", ""),
        timeout=Env.get_int("OMICS_REQUEST_TIMEOUT", 60),
    )


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


def _set_relation_status(dataset: Any, status: str, error: Optional[str] = None) -> None:
    for batch in dataset.omics_batch.all():
        if batch.status != "RUNNING":
            continue
        relation = dataset.omics_batch.relationship(batch)
        relation.status = status
        if error is not None:
            relation.error_message = error
        relation.save()


def send_fetch(dataset_uuid: str) -> str:
    task = celery.get_instance().celery_app.send_task(
        FETCH_TASK, args=(dataset_uuid,), countdown=1
    )
    return str(task.id)


def poll_tasks(
    graph: Any,
    client: Any,
    send_task: Callable[[str], str] = send_fetch,
    now: Optional[datetime] = None,
) -> Dict[str, List[str]]:
    """Synchronize active NIG datasets with their authoritative Omics status."""
    timestamp = _now(now)
    report = {"submitted": [], "running": [], "fetching": [], "failed": []}
    datasets = graph.Dataset.nodes.filter(omics_task_id__isnull=False).all()
    for dataset in datasets:
        if dataset.omics_status not in POLLABLE:
            continue
        remote = client.get_task(dataset.omics_task_id)
        status = remote.status.lower()
        if status in ("pending", "received"):
            local_status = SUBMITTED
        elif status == "processing":
            local_status = RUNNING
        elif status == "complete":
            # Do not mark FETCHING until Celery has accepted the message; if
            # dispatch fails, the next poll safely tries again.
            try:
                send_task(str(dataset.uuid))
            except Exception as exc:
                log.error("Cannot enqueue fetch for Omics dataset {}: {}", dataset.uuid, exc)
                continue
            local_status = FETCHING
        elif status == "error":
            message = "Omics remote task reported Error"
            dataset.status = ERROR
            dataset.status_update = timestamp
            dataset.error_message = message
            dataset.omics_status = ERROR
            dataset.omics_status_update = timestamp
            dataset.omics_error_message = message
            dataset.save()
            _set_relation_status(dataset, ERROR, message)
            _notify_error(dataset, message)
            report["failed"].append(str(dataset.uuid))
            continue
        else:
            log.warning("Unknown Omics task status '{}' for {}", remote.status, dataset.uuid)
            continue

        dataset.status = RUNNING
        dataset.status_update = timestamp
        dataset.omics_status = local_status
        dataset.omics_status_update = timestamp
        dataset.save()
        _set_relation_status(dataset, local_status)
        report[local_status.lower()].append(str(dataset.uuid))
    return report


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def omics_poll_tasks(self: Task[[], None]) -> None:
    report = poll_tasks(neo4j.get_instance(), _client_from_env())
    log.info("Omics poll completed: {}", report)
