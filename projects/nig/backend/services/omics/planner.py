"""Quota-aware batch planning for Omics (pure logic, no I/O).

The caller provides the authoritative remote ``quota``/``usage`` read from
``GET /storage/objects/usage`` (plus any bytes already reserved by NIG batches
not yet uploaded); this module only decides which datasets fit.

Algorithm:

* ``capacity = quota * (1 - margin)``; ``usable = capacity - used``;
* datasets are visited FIFO by readiness date, tie-break on size ascending
  (then uuid, for a deterministic order);
* a dataset larger than ``capacity`` can never fit: it is reported as
  ``oversized`` so the caller can flag it, instead of blocking the queue;
* a dataset that does not fit in the remaining space is ``deferred``: it keeps
  its status and will be considered again by the next run.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class DatasetCandidate:
    uuid: str
    size_bytes: int
    # when the dataset became ready (``UPLOAD COMPLETED``); None sorts last
    ready_at: Optional[datetime] = None


@dataclass
class BatchPlan:
    capacity_bytes: int
    usable_bytes: int
    planned_bytes: int = 0
    selected: List[str] = field(default_factory=list)
    deferred: List[str] = field(default_factory=list)
    oversized: List[str] = field(default_factory=list)


def effective_quota(remote_quota: Optional[int], expected_quota: int) -> int:
    """The remote quota is authoritative; fall back to the agreed value."""
    if remote_quota and remote_quota > 0:
        return int(remote_quota)
    return int(expected_quota)


def _fifo_key(candidate: DatasetCandidate) -> Tuple[bool, float, int, str]:
    ready = candidate.ready_at.timestamp() if candidate.ready_at else 0.0
    return (candidate.ready_at is None, ready, candidate.size_bytes, candidate.uuid)


def plan_batch(
    datasets: Iterable[DatasetCandidate],
    quota_bytes: int,
    used_bytes: int,
    safety_margin_pct: float,
) -> BatchPlan:
    if quota_bytes <= 0:
        raise ValueError("quota_bytes must be positive")
    if used_bytes < 0:
        raise ValueError("used_bytes cannot be negative")
    if not 0 <= safety_margin_pct < 100:
        raise ValueError("safety_margin_pct must be in [0, 100)")

    candidates = list(datasets)
    for candidate in candidates:
        if candidate.size_bytes <= 0:
            raise ValueError(f"Dataset {candidate.uuid} has an invalid size")

    capacity = int(quota_bytes * (100 - safety_margin_pct) // 100)
    usable = max(capacity - used_bytes, 0)
    plan = BatchPlan(capacity_bytes=capacity, usable_bytes=usable)

    for candidate in sorted(candidates, key=_fifo_key):
        if candidate.size_bytes > capacity:
            plan.oversized.append(candidate.uuid)
        elif plan.planned_bytes + candidate.size_bytes > usable:
            plan.deferred.append(candidate.uuid)
        else:
            plan.selected.append(candidate.uuid)
            plan.planned_bytes += candidate.size_bytes

    return plan
