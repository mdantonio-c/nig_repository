#!/usr/bin/env python3
"""Plan and dispatch Omics/Parabricks batches for ``genome`` datasets.

Counterpart of ``init_pipeline.py`` (which only handles ``exome`` studies).
Selects genome datasets in ``UPLOAD COMPLETED``, reads the authoritative
remote quota from ``GET /storage/objects/usage`` and plans a batch that fits
(``services/omics/planner.py``). Then, unless ``--dry-run`` is given:

1. datasets larger than the whole quota are flagged ``ERROR`` and the NIG
   admin is notified;
2. the selected datasets are claimed atomically (see ``CLAIM_QUERY``) and
   linked to a new ``OmicsBatch`` in ``PLANNED`` status;
3. the ``omics_run_batch`` Celery task is sent for that batch.

Concurrency: every mutating statement first write-locks the
singleton ``OmicsDispatcherLock`` node, so concurrent runs are serialised by
Neo4j. Inside the locked statement the claim re-checks the number of active
batches (``OMICS_MAX_CONCURRENT_BATCHES``), the bytes they still reserve
(optimistic check against the value used for planning) and each dataset
status, so a stale plan claims nothing instead of double-booking quota.

With ``OMICS_ENABLE=0`` (default) the script exits immediately.

Run via
``rapydo shell backend "python3 /code/nig/scripts/init_omics_pipeline.py --dry-run"``.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pytz
from nig.services.omics import OmicsClient
from nig.services.omics.planner import DatasetCandidate, effective_quota, plan_batch
from restapi.connectors import celery, neo4j
from restapi.connectors.smtp.notifications import send_notification
from restapi.env import Env
from restapi.utilities.logs import log
from restapi.utilities.uuid import getUUID

REPORT_TYPE = "nig_omics_dispatch"
OMICS_STUDY_TYPE = "genome"
READY_STATUS = "UPLOAD COMPLETED"
QUEUED_STATUS = "QUEUED"
RUN_BATCH_TASK = "omics_run_batch"
LOCK_NAME = "omics_dispatcher"
OVERSIZED_ERROR = "Dataset larger than the Omics storage quota"

# batches still holding (or about to hold) remote quota
ACTIVE_BATCH_STATUSES = ["PLANNED", "RUNNING"]
# dataset omics states owned by an in-flight batch: never claimable again
ACTIVE_OMICS_STATUSES = [
    "QUEUED",
    "UPLOADING",
    "SUBMITTED",
    "RUNNING",
    "FETCHING",
    "CLEANING",
]

# The lock node is created by its own auto-commit statement (ENSURE_LOCK_QUERY):
# a MERGE inside the claim would let two first-time runs each create (and
# lock) a private node. Every mutating statement then write-locks all lock
# nodes (duplicates are harmless: all of them are locked) and aggregates, so
# every read below runs after the lock is held and sees the committed state
# of the previous run. A missing lock node makes the statement a no-op.
ENSURE_LOCK_QUERY = "MERGE (lock:OmicsDispatcherLock {name: $lock_name})"

LOCK_CLAUSE = """
MATCH (lock:OmicsDispatcherLock {name: $lock_name})
SET lock.locked_at = $now, lock.holder = $holder
WITH count(lock) AS locked
WHERE locked > 0
"""

CLAIM_QUERY = (
    LOCK_CLAUSE
    + """
OPTIONAL MATCH (active:OmicsBatch)
WHERE active.status IN $active_batch_statuses
WITH count(active) AS active_count,
     sum(CASE
           WHEN coalesce(active.planned_bytes, 0) > coalesce(active.uploaded_bytes, 0)
           THEN coalesce(active.planned_bytes, 0) - coalesce(active.uploaded_bytes, 0)
           ELSE 0
         END) AS reserved
WHERE active_count < $max_batches AND reserved = $expected_reserved
MATCH (d:Dataset)
WHERE d.uuid IN $dataset_uuids
  AND d.status = $ready_status
  AND (d.omics_status IS NULL OR NOT d.omics_status IN $active_omics_statuses)
WITH collect(d) AS claimed
WHERE size(claimed) > 0
CREATE (b:OmicsBatch {
    uuid: $holder,
    status: 'PLANNED',
    planned_bytes: reduce(total = 0, x IN claimed | total + $sizes[x.uuid]),
    uploaded_bytes: 0,
    created: $now,
    modified: $now
})
WITH b, claimed
UNWIND claimed AS d
SET d.status = $queued_status,
    d.status_update = $now,
    d.omics_status = $queued_status,
    d.omics_status_update = $now,
    d.omics_error_message = null,
    d.modified = $now
CREATE (d)-[:SENT_TO_OMICS {status: $queued_status}]->(b)
RETURN d.uuid
"""
)

RELEASE_QUERY = (
    LOCK_CLAUSE
    + """
MATCH (b:OmicsBatch {uuid: $holder})
SET b.status = 'ERROR', b.modified = $now
WITH b
MATCH (d:Dataset)-[r:SENT_TO_OMICS]->(b)
WHERE d.status = $queued_status AND d.omics_status = $queued_status
SET d.status = $ready_status,
    d.status_update = $now,
    d.omics_status = null,
    d.omics_status_update = $now,
    d.modified = $now,
    r.status = 'ERROR',
    r.error_message = $reason
RETURN d.uuid
"""
)

REJECT_QUERY = (
    LOCK_CLAUSE
    + """
MATCH (d:Dataset)
WHERE d.uuid IN $dataset_uuids AND d.status = $ready_status
SET d.status = 'ERROR',
    d.error_message = $message,
    d.status_update = $now,
    d.omics_status = 'ERROR',
    d.omics_error_message = $message,
    d.omics_status_update = $now,
    d.modified = $now
RETURN d.uuid
"""
)


@dataclass
class DispatcherSettings:
    enabled: bool
    api_url: str
    username: str
    password: str
    request_timeout: int
    expected_quota_bytes: int
    safety_margin_pct: int
    max_concurrent_batches: int
    batch_stale_hours: int

    @classmethod
    def from_env(cls) -> "DispatcherSettings":
        return cls(
            enabled=Env.get_bool("OMICS_ENABLE", False),
            api_url=Env.get("OMICS_API_URL", ""),
            username=Env.get("OMICS_USERNAME", ""),
            password=Env.get("OMICS_PASSWORD", ""),
            request_timeout=Env.get_int("OMICS_REQUEST_TIMEOUT", 60),
            expected_quota_bytes=Env.get_int(
                "OMICS_EXPECTED_QUOTA_BYTES", 1_000_000_000_000
            ),
            safety_margin_pct=Env.get_int("OMICS_QUOTA_SAFETY_MARGIN_PCT", 5),
            max_concurrent_batches=Env.get_int("OMICS_MAX_CONCURRENT_BATCHES", 1),
            batch_stale_hours=Env.get_int("OMICS_BATCH_STALE_HOURS", 48),
        )


def ensure_lock(graph: Any) -> None:
    graph.cypher(ENSURE_LOCK_QUERY, lock_name=LOCK_NAME)


def _locked_rows(graph: Any, query: str, **params: Any) -> List[str]:
    ensure_lock(graph)
    return [row[0] for row in graph.cypher(query, lock_name=LOCK_NAME, **params)]


def select_omics_datasets(datasets: Sequence[Any]) -> List[Any]:
    """Keep only genome datasets not already owned by an in-flight batch."""
    selected = []
    for dataset in datasets:
        study = dataset.parent_study.single()
        if study is None or study.study_type != OMICS_STUDY_TYPE:
            continue
        if dataset.omics_status in ACTIVE_OMICS_STATUSES:
            # inconsistent (ready locally but active remotely): fail closed
            log.warning(
                "Dataset {} is {} but omics_status is {}, skipping",
                dataset.uuid,
                dataset.status,
                dataset.omics_status,
            )
            continue
        selected.append(dataset)
    return selected


def dataset_size(dataset: Any) -> Optional[int]:
    """Sum of the dataset FASTQ sizes; None if unknown or empty."""
    files = dataset.files.all()
    if not files:
        return None
    sizes = [f.size for f in files]
    if any(size is None or size <= 0 for size in sizes):
        return None
    return int(sum(sizes))


def build_candidates(
    datasets: Sequence[Any],
) -> Tuple[List[DatasetCandidate], List[str]]:
    candidates: List[DatasetCandidate] = []
    invalid: List[str] = []
    for dataset in datasets:
        size = dataset_size(dataset)
        if size is None:
            log.warning("Dataset {} has no valid file sizes, skipping", dataset.uuid)
            invalid.append(str(dataset.uuid))
            continue
        candidates.append(
            DatasetCandidate(
                uuid=str(dataset.uuid),
                size_bytes=size,
                ready_at=dataset.status_update or dataset.created,
            )
        )
    return candidates, invalid


def find_active_batches(graph: Any) -> List[Any]:
    return list(graph.OmicsBatch.nodes.filter(status__in=ACTIVE_BATCH_STATUSES).all())


def reserved_bytes(batches: Sequence[Any]) -> int:
    """Bytes planned by active batches and not yet reflected in remote usage.

    Must match the ``reserved`` expression of ``CLAIM_QUERY``.
    """
    return sum(
        max((b.planned_bytes or 0) - (b.uploaded_bytes or 0), 0) for b in batches
    )


def find_stale_batches(
    batches: Sequence[Any], now: datetime, stale_hours: int
) -> List[str]:
    threshold = now - timedelta(hours=stale_hours)
    return [str(b.uuid) for b in batches if b.created and b.created < threshold]


def claim_batch(
    graph: Any,
    batch_uuid: str,
    sizes: Dict[str, int],
    max_batches: int,
    expected_reserved: int,
    now: datetime,
) -> List[str]:
    """Atomically create the batch and claim its datasets.

    Returns the claimed dataset uuids; empty if another run changed the state
    since planning (nothing is written in that case).
    """
    return _locked_rows(
        graph,
        CLAIM_QUERY,
        holder=batch_uuid,
        now=now.timestamp(),
        active_batch_statuses=ACTIVE_BATCH_STATUSES,
        max_batches=max_batches,
        expected_reserved=expected_reserved,
        dataset_uuids=list(sizes),
        sizes=sizes,
        ready_status=READY_STATUS,
        queued_status=QUEUED_STATUS,
        active_omics_statuses=ACTIVE_OMICS_STATUSES,
    )


def release_batch(graph: Any, batch_uuid: str, reason: str, now: datetime) -> List[str]:
    """Undo a claim whose task could not be sent: datasets become ready again."""
    return _locked_rows(
        graph,
        RELEASE_QUERY,
        holder=batch_uuid,
        now=now.timestamp(),
        ready_status=READY_STATUS,
        queued_status=QUEUED_STATUS,
        reason=reason,
    )


def reject_oversized(graph: Any, dataset_uuids: List[str], now: datetime) -> List[str]:
    if not dataset_uuids:
        return []
    return _locked_rows(
        graph,
        REJECT_QUERY,
        holder="reject-oversized",
        now=now.timestamp(),
        dataset_uuids=dataset_uuids,
        ready_status=READY_STATUS,
        message=OVERSIZED_ERROR,
    )


def notify_oversized(graph: Any, dataset_uuid: str) -> None:
    dataset = graph.Dataset.nodes.get_or_none(uuid=dataset_uuid)
    if dataset is None:
        return
    study = dataset.parent_study.single()
    send_notification(
        subject="A dataset cannot be analysed on Omics",
        template="dataset_error.html",
        to_address=None,
        data={
            "dataset_id": dataset.uuid,
            "dataset_name": dataset.name,
            "study_id": study.uuid if study else "N/A",
            "study_name": study.name if study else "N/A",
            "error_message": OVERSIZED_ERROR,
            "output_path": "N/A",
            "job_path": "N/A",
        },
    )


def send_run_batch(batch_uuid: str, dataset_uuids: List[str]) -> str:
    c = celery.get_instance()
    task = c.celery_app.send_task(
        RUN_BATCH_TASK, args=(batch_uuid, dataset_uuids), countdown=1
    )
    return str(task)


def run(
    graph: Any,
    client: Any,
    settings: DispatcherSettings,
    dry_run: bool,
    now: datetime,
    send_task: Callable[[str, List[str]], str] = send_run_batch,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "report_type": REPORT_TYPE,
        "dry_run": dry_run,
        "generated_at": now.isoformat(),
        "batch": None,
        "skipped_reason": None,
    }

    active = find_active_batches(graph)
    stale = find_stale_batches(active, now, settings.batch_stale_hours)
    for batch_uuid in stale:
        log.warning(
            "Omics batch {} is active since more than {}h: possibly stuck",
            batch_uuid,
            settings.batch_stale_hours,
        )
    report["active_batches"] = [str(b.uuid) for b in active]
    report["stale_batches"] = stale

    if len(active) >= settings.max_concurrent_batches:
        report["skipped_reason"] = "max concurrent batches reached"
        return report

    reserved = reserved_bytes(active)
    ready = graph.Dataset.nodes.filter(status=READY_STATUS).all()
    candidates, invalid = build_candidates(select_omics_datasets(ready))
    report["invalid_datasets"] = invalid
    if not candidates:
        report["skipped_reason"] = "no genome datasets ready"
        return report

    usage = client.get_storage_usage()
    report["storage"] = asdict(usage)
    if not usage.can_upload:
        report["skipped_reason"] = "remote storage does not accept uploads"
        return report

    if usage.quota and usage.quota != settings.expected_quota_bytes:
        log.warning(
            "Omics quota {} differs from the expected {}",
            usage.quota,
            settings.expected_quota_bytes,
        )
    quota = effective_quota(usage.quota, settings.expected_quota_bytes)
    plan = plan_batch(
        candidates, quota, usage.usage + reserved, settings.safety_margin_pct
    )
    report["reserved_bytes"] = reserved
    report["plan"] = asdict(plan)

    if dry_run:
        return report

    rejected = reject_oversized(graph, plan.oversized, now)
    for dataset_uuid in rejected:
        log.error("Dataset {}: {}", dataset_uuid, OVERSIZED_ERROR)
        try:
            notify_oversized(graph, dataset_uuid)
        except Exception as exc:  # notification must not stop dispatching
            log.error("Notification for dataset {} failed: {}", dataset_uuid, exc)
    report["rejected_datasets"] = rejected

    if not plan.selected:
        report["skipped_reason"] = "no dataset fits the available quota"
        return report

    batch_uuid = getUUID()
    sizes = {c.uuid: c.size_bytes for c in candidates if c.uuid in plan.selected}
    claimed = claim_batch(
        graph, batch_uuid, sizes, settings.max_concurrent_batches, reserved, now
    )
    if not claimed:
        report["skipped_reason"] = "state changed by a concurrent run, nothing claimed"
        return report

    try:
        task_id = send_task(batch_uuid, claimed)
    except Exception as exc:
        log.error("Cannot send {} for batch {}: {}", RUN_BATCH_TASK, batch_uuid, exc)
        release_batch(graph, batch_uuid, "Task submission failed", now)
        report["skipped_reason"] = "task submission failed, claim released"
        return report

    log.info("{} datasets sent to Omics batch {}", len(claimed), batch_uuid)
    report["batch"] = {"uuid": batch_uuid, "datasets": claimed, "task": task_id}
    return report


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the batch that would be created, without writing or sending",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    settings = DispatcherSettings.from_env()
    if not settings.enabled:
        log.info("OMICS_ENABLE is off, Omics dispatcher not executed")
        return 0
    if not (settings.api_url and settings.username and settings.password):
        log.error("OMICS_API_URL, OMICS_USERNAME and OMICS_PASSWORD are required")
        return 1

    client = OmicsClient(
        settings.api_url,
        settings.username,
        settings.password,
        timeout=settings.request_timeout,
    )
    report = run(
        neo4j.get_instance(),
        client,
        settings,
        dry_run=args.dry_run,
        now=datetime.now(pytz.utc),
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
