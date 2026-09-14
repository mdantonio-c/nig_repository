"""Unit tests for :mod:`nig.scripts.migrate_study_type`.

These tests exercise the migration logic against fake graph/query objects
(mirroring the approach used for the admin-hierarchy migration scripts) so they
run without a live Neo4j connection. End-to-end behavior against the real
Study model/API is covered by ``test_api_study.py``.
"""

import json
import stat
from typing import Dict, List, Optional

import pytest

from nig.scripts import migrate_study_type
from nig.scripts.migrate_study_type import (
    DEFAULT_STUDY_TYPE,
    REPORT_TYPE,
    apply_migration,
    build_plan,
    rollback_migration,
)


class FakeStudy:
    def __init__(self, uuid: str, study_type: Optional[str] = None) -> None:
        self.uuid = uuid
        self.study_type = study_type
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1


class FakeNodeSet:
    def __init__(self, registry: Dict[str, FakeStudy], only_null: bool = False) -> None:
        self._registry = registry
        self._only_null = only_null

    def filter(self, **kwargs: object) -> "FakeNodeSet":
        assert kwargs == {"study_type__isnull": True}
        return FakeNodeSet(self._registry, only_null=True)

    def all(self) -> List[FakeStudy]:
        studies = list(self._registry.values())
        if self._only_null:
            studies = [s for s in studies if s.study_type is None]
        return studies

    def get_or_none(self, uuid: str) -> Optional[FakeStudy]:
        return self._registry.get(uuid)


class FakeStudyManager:
    def __init__(self, registry: Dict[str, FakeStudy]) -> None:
        self.nodes = FakeNodeSet(registry)


class FakeGraph:
    def __init__(self, studies: List[FakeStudy]) -> None:
        self.registry = {s.uuid: s for s in studies}
        self.Study = FakeStudyManager(self.registry)


class FakeTransaction:
    def begin(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def _patch_transaction(monkeypatch) -> None:
    monkeypatch.setattr(migrate_study_type, "neo4j_db", FakeTransaction())


def test_build_plan_lists_only_studies_without_type() -> None:
    graph = FakeGraph(
        [
            FakeStudy("legacy-1", study_type=None),
            FakeStudy("legacy-2", study_type=None),
            FakeStudy("typed-1", study_type="genome"),
        ]
    )

    plan = build_plan(graph)

    assert plan["read_only"] is True
    assert plan["count"] == 2
    assert plan["studies_to_migrate"] == ["legacy-1", "legacy-2"]
    assert plan["default_study_type"] == DEFAULT_STUDY_TYPE
    # dry-run never mutates
    assert graph.registry["legacy-1"].save_calls == 0
    assert graph.registry["legacy-2"].save_calls == 0


def test_apply_migration_normalizes_and_writes_protected_report(
    monkeypatch, tmp_path
) -> None:
    _patch_transaction(monkeypatch)
    graph = FakeGraph(
        [
            FakeStudy("legacy-1", study_type=None),
            FakeStudy("typed-1", study_type="genome"),
        ]
    )
    report_path = tmp_path.joinpath("report.json")

    result = apply_migration(graph, report_path)

    assert result["changed_studies"] == 1
    assert graph.registry["legacy-1"].study_type == DEFAULT_STUDY_TYPE
    assert graph.registry["legacy-1"].save_calls == 1
    # untouched study is not saved again
    assert graph.registry["typed-1"].save_calls == 0

    assert report_path.is_file()
    mode = stat.S_IMODE(report_path.stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR

    report = json.loads(report_path.read_text())
    assert report["report_type"] == REPORT_TYPE
    assert report["applied_study_type"] == DEFAULT_STUDY_TYPE
    assert report["studies"] == ["legacy-1"]


def test_apply_migration_is_idempotent(monkeypatch, tmp_path) -> None:
    _patch_transaction(monkeypatch)
    graph = FakeGraph([FakeStudy("legacy-1", study_type=None)])
    report_path = tmp_path.joinpath("report.json")

    first = apply_migration(graph, report_path)
    assert first["changed_studies"] == 1

    second_report_path = tmp_path.joinpath("report-2.json")
    second = apply_migration(graph, second_report_path)

    assert second["changed_studies"] == 0
    assert json.loads(second_report_path.read_text())["studies"] == []


def test_rollback_restores_only_untouched_migrated_studies(
    monkeypatch, tmp_path
) -> None:
    _patch_transaction(monkeypatch)
    graph = FakeGraph(
        [
            FakeStudy("legacy-1", study_type=None),
            FakeStudy("legacy-2", study_type=None),
        ]
    )
    report_path = tmp_path.joinpath("report.json")
    apply_migration(graph, report_path)

    # simulate a manual change made after the migration on one of the studies
    graph.registry["legacy-2"].study_type = "genome"

    report = json.loads(report_path.read_text())
    result = rollback_migration(graph, report)

    assert result["restored_studies"] == 1
    assert result["skipped_studies"] == 1
    assert graph.registry["legacy-1"].study_type is None
    # left untouched because it no longer matches the applied value
    assert graph.registry["legacy-2"].study_type == "genome"


def test_rollback_rejects_foreign_report() -> None:
    with pytest.raises(ValueError):
        rollback_migration(FakeGraph([]), {"report_type": "something_else"})
