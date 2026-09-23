"""Unit tests for the pure Omics batch planner."""

from datetime import datetime, timedelta

import pytest
import pytz
from nig.services.omics.planner import (
    BatchPlan,
    DatasetCandidate,
    effective_quota,
    plan_batch,
)

T0 = datetime(2026, 1, 1, tzinfo=pytz.utc)
QUOTA = 1000
MARGIN = 5  # capacity = 950


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_empty_list_returns_empty_plan() -> None:
    plan = plan_batch([], QUOTA, 0, MARGIN)

    assert plan == BatchPlan(capacity_bytes=950, usable_bytes=950)


def test_fifo_order_by_readiness_date() -> None:
    datasets = [
        DatasetCandidate("newer", 100, at(10)),
        DatasetCandidate("older", 300, at(0)),
        DatasetCandidate("middle", 200, at(5)),
    ]

    plan = plan_batch(datasets, QUOTA, 0, MARGIN)

    assert plan.selected == ["older", "middle", "newer"]
    assert plan.planned_bytes == 600


def test_same_date_tie_break_on_size_ascending() -> None:
    datasets = [
        DatasetCandidate("big", 500, at(0)),
        DatasetCandidate("small", 100, at(0)),
        DatasetCandidate("medium", 300, at(0)),
    ]

    plan = plan_batch(datasets, QUOTA, 0, MARGIN)

    assert plan.selected == ["small", "medium", "big"]


def test_datasets_without_date_come_last() -> None:
    datasets = [
        DatasetCandidate("undated", 100, None),
        DatasetCandidate("dated", 100, at(0)),
    ]

    plan = plan_batch(datasets, QUOTA, 0, MARGIN)

    assert plan.selected == ["dated", "undated"]


def test_fill_skips_what_does_not_fit_and_takes_later_smaller_ones() -> None:
    datasets = [
        DatasetCandidate("first", 600, at(0)),
        DatasetCandidate("too-big-now", 400, at(1)),
        DatasetCandidate("fits", 300, at(2)),
        DatasetCandidate("no-room-left", 100, at(3)),
    ]

    plan = plan_batch(datasets, QUOTA, 0, MARGIN)

    assert plan.selected == ["first", "fits"]
    assert plan.deferred == ["too-big-now", "no-room-left"]
    assert plan.planned_bytes == 900
    assert plan.oversized == []


def test_dataset_larger_than_quota_is_flagged_and_does_not_block_queue() -> None:
    datasets = [
        DatasetCandidate("huge", 951, at(0)),
        DatasetCandidate("normal", 100, at(1)),
    ]

    plan = plan_batch(datasets, QUOTA, 0, MARGIN)

    assert plan.oversized == ["huge"]
    assert plan.selected == ["normal"]
    assert plan.deferred == []


def test_oversized_is_relative_to_quota_not_to_free_space() -> None:
    # 900 does not fit now (usage 500) but will fit once quota is released:
    # it must be deferred, not flagged as oversized
    plan = plan_batch([DatasetCandidate("later", 900, at(0))], QUOTA, 500, MARGIN)

    assert plan.deferred == ["later"]
    assert plan.oversized == []


def test_safety_margin_boundary() -> None:
    plan = plan_batch([DatasetCandidate("exact", 950, at(0))], QUOTA, 0, MARGIN)
    assert plan.selected == ["exact"]

    plan = plan_batch([DatasetCandidate("over", 951, at(0))], QUOTA, 0, MARGIN)
    assert plan.oversized == ["over"]


def test_zero_margin_uses_full_quota() -> None:
    plan = plan_batch([DatasetCandidate("full", 1000, at(0))], QUOTA, 0, 0)

    assert plan.capacity_bytes == 1000
    assert plan.selected == ["full"]


def test_used_bytes_reduce_usable_space() -> None:
    datasets = [
        DatasetCandidate("a", 60, at(0)),
        DatasetCandidate("b", 50, at(1)),
    ]

    plan = plan_batch(datasets, QUOTA, 900, MARGIN)

    assert plan.usable_bytes == 50
    assert plan.selected == ["b"]
    assert plan.deferred == ["a"]


def test_saturated_quota_defers_everything() -> None:
    datasets = [DatasetCandidate("a", 10, at(0)), DatasetCandidate("b", 20, at(1))]

    plan = plan_batch(datasets, QUOTA, 990, MARGIN)

    assert plan.usable_bytes == 0
    assert plan.selected == []
    assert plan.deferred == ["a", "b"]
    assert plan.planned_bytes == 0


def test_plan_is_deterministic() -> None:
    datasets = [DatasetCandidate(f"d{i}", 10 + i % 3, at(i % 2)) for i in range(20)]

    first = plan_batch(datasets, QUOTA, 0, MARGIN)
    second = plan_batch(list(reversed(datasets)), QUOTA, 0, MARGIN)

    assert first == second


@pytest.mark.parametrize(
    "quota,used,margin",
    [(0, 0, 5), (-1, 0, 5), (1000, -1, 5), (1000, 0, -1), (1000, 0, 100)],
)
def test_invalid_parameters_are_rejected(quota: int, used: int, margin: int) -> None:
    with pytest.raises(ValueError):
        plan_batch([], quota, used, margin)


@pytest.mark.parametrize("size", [0, -10])
def test_invalid_dataset_size_is_rejected(size: int) -> None:
    with pytest.raises(ValueError):
        plan_batch([DatasetCandidate("bad", size, at(0))], QUOTA, 0, MARGIN)


def test_effective_quota_prefers_remote_value() -> None:
    assert effective_quota(2000, 1000) == 2000


@pytest.mark.parametrize("remote", [None, 0])
def test_effective_quota_falls_back_to_expected(remote: int) -> None:
    assert effective_quota(remote, 1000) == 1000
