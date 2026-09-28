"""Batch/relationship state shared by the Omics Celery tasks.

The ``SENT_TO_OMICS`` relationship status is the authority on what a batch
still owns: a dataset requeued for quota keeps the dataset node reusable by a
later batch, but its relationship with the old batch is closed. A batch is
closed only when all its relationships are closed, from whichever task
produced the last terminal transition.
"""

from typing import Any, List, Optional

ACTIVE_BATCH_STATUSES = ("PLANNED", "RUNNING")
COMPLETED = "COMPLETED"
ERROR = "ERROR"
# Closed batch whose datasets did not all complete: some were released.
PARTIAL = "PARTIAL"
# Relationship released back to the dispatcher (quota requeue).
RELEASED = "UPLOAD COMPLETED"
CLOSED_RELATION_STATUSES = (COMPLETED, ERROR, RELEASED)
# Dataset omics states owned by an in-flight batch or by a remote task.
ACTIVE_DATASET_STATUSES = (
    "QUEUED",
    "UPLOADING",
    "SUBMITTING",
    "SUBMIT_UNKNOWN",
    "SUBMITTED",
    "RUNNING",
    "FETCHING",
    "CLEANUP PENDING",
    "CLEANING",
)


def active_relations(dataset: Any) -> Any:
    """Yield ``(batch, relation)`` pairs still owned by an active batch."""
    for batch in dataset.omics_batch.all():
        if batch.status not in ACTIVE_BATCH_STATUSES:
            continue
        relation = dataset.omics_batch.relationship(batch)
        if relation is None or relation.status in CLOSED_RELATION_STATUSES:
            continue
        yield batch, relation


def set_relation_status(
    dataset: Any, status: str, error: Optional[str] = None
) -> None:
    for batch, relation in list(active_relations(dataset)):
        relation.status = status
        if error is not None:
            relation.error_message = error
        relation.save()
        finalize_batch(batch)


def omics_locked(dataset: Any) -> bool:
    """True while the Omics pipeline owns the dataset (it must not be changed)."""
    if dataset.omics_status in ACTIVE_DATASET_STATUSES:
        return True
    return next(iter(active_relations(dataset)), None) is not None


def batch_outcome(batch: Any) -> Optional[str]:
    """Final status ``batch`` should take, or ``None`` while it must stay active.

    * any ``ERROR`` relationship -> ``ERROR``;
    * all relationships ``COMPLETED`` -> ``COMPLETED``;
    * otherwise (some released for quota) -> ``PARTIAL``;
    * no relationship left (datasets deleted) -> ``ERROR``.

    ``SUBMIT_UNKNOWN`` deliberately keeps the batch active: the remote task may
    exist and still hold quota, so it requires manual reconciliation.
    """
    if batch.status not in ACTIVE_BATCH_STATUSES:
        return None
    statuses: List[Optional[str]] = []
    for member in batch.datasets.all():
        relation = batch.datasets.relationship(member)
        statuses.append(relation.status if relation is not None else None)
    if any(s not in CLOSED_RELATION_STATUSES for s in statuses):
        return None
    if not statuses or ERROR in statuses:
        return ERROR
    if all(s == COMPLETED for s in statuses):
        return COMPLETED
    return PARTIAL


def finalize_batch(batch: Any) -> Optional[str]:
    """Close ``batch`` when none of its relationships is still open.

    Returns the new batch status, or ``None`` when the batch stays active.
    """
    outcome = batch_outcome(batch)
    if outcome is None:
        return None
    batch.status = outcome
    batch.save()
    return outcome
