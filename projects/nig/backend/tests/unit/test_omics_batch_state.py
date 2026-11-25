"""Tests for the Omics batch closure rules and the dataset edit lock."""

from dataclasses import dataclass, field
from typing import Any, List, Optional

import pytest
from nig.services.omics.batch_state import (
    batch_outcome,
    finalize_batch,
    omics_locked,
)


@dataclass
class Relation:
    status: str


class Members:
    def __init__(self, relations: List[Relation]) -> None:
        self.relations = relations

    def all(self) -> List[Relation]:
        return list(self.relations)

    def relationship(self, member: Relation) -> Relation:
        return member


@dataclass
class Batch:
    relation_statuses: List[str] = field(default_factory=list)
    status: str = "RUNNING"
    saves: int = 0

    @property
    def datasets(self) -> Members:
        return Members([Relation(s) for s in self.relation_statuses])

    def save(self) -> None:
        self.saves += 1


class DatasetBatches:
    def __init__(self, batch: Optional[Batch], relation: Optional[Relation]) -> None:
        self.batch = batch
        self.relation = relation

    def all(self) -> List[Batch]:
        return [self.batch] if self.batch else []

    def relationship(self, batch: Batch) -> Optional[Relation]:
        return self.relation


class Dataset:
    def __init__(
        self,
        omics_status: Optional[str] = None,
        batch: Optional[Batch] = None,
        relation: Optional[str] = None,
    ) -> None:
        self.omics_status = omics_status
        self.omics_batch = DatasetBatches(
            batch, Relation(relation) if relation else None
        )


@pytest.mark.parametrize(
    "statuses, expected",
    [
        (["COMPLETED", "COMPLETED"], "COMPLETED"),
        (["COMPLETED", "ERROR"], "ERROR"),
        (["ERROR", "UPLOAD COMPLETED"], "ERROR"),
        (["COMPLETED", "UPLOAD COMPLETED"], "PARTIAL"),
        (["UPLOAD COMPLETED"], "PARTIAL"),
        ([], "ERROR"),
        (["COMPLETED", "RUNNING"], None),
        (["COMPLETED", "SUBMIT_UNKNOWN"], None),
        (["QUEUED"], None),
    ],
)
def test_batch_outcome(statuses: List[str], expected: Optional[str]) -> None:
    assert batch_outcome(Batch(statuses)) == expected


def test_closed_batch_is_never_reclosed() -> None:
    batch = Batch(["ERROR"], status="COMPLETED")

    assert batch_outcome(batch) is None
    assert finalize_batch(batch) is None
    assert batch.status == "COMPLETED" and batch.saves == 0


def test_finalize_saves_the_outcome() -> None:
    batch = Batch(["COMPLETED", "UPLOAD COMPLETED"])

    assert finalize_batch(batch) == "PARTIAL"
    assert batch.status == "PARTIAL" and batch.saves == 1


@pytest.mark.parametrize(
    "dataset, locked",
    [
        (Dataset(), False),
        (Dataset("COMPLETED"), False),
        (Dataset("ERROR"), False),
        (Dataset("RUNNING"), True),
        (Dataset("SUBMIT_UNKNOWN"), True),
        (Dataset("CLEANUP PENDING"), True),
        # open claim of an active batch, whatever the dataset fields say
        (Dataset(None, Batch(["QUEUED"]), "QUEUED"), True),
        (Dataset(None, Batch(["UPLOAD COMPLETED"]), "UPLOAD COMPLETED"), False),
        (Dataset(None, Batch(["QUEUED"], status="ERROR"), "QUEUED"), False),
    ],
)
def test_omics_locked(dataset: Dataset, locked: bool) -> None:
    assert omics_locked(dataset) is locked
