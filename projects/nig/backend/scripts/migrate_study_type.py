#!/usr/bin/env python3
"""Backfill ``study_type`` on existing ``Study`` nodes.

``Study.study_type`` is a required property introduced for issue #60. Studies
created before this change have no value for it. This script normalizes them to
``"exome"`` (the only type that existed before genome support was introduced).

Modes:

* ``--dry-run`` (default): only reports how many/which studies would be
  changed. Never writes to Neo4j.
* ``--apply``: performs the update inside a single transaction and writes a
  protected (``0600``) report of the touched uuids to ``--report`` so the
  change can be rolled back.
* ``--rollback <report>``: removes ``study_type`` only from the uuids listed in
  the given report file, and only if the current value still matches what the
  migration set.

Run via ``rapydo shell backend "python3 /code/nig/scripts/migrate_study_type.py --dry-run"``.
"""

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from restapi.connectors import neo4j
from restapi.utilities.logs import log

try:
    from neomodel import db as neo4j_db
except ModuleNotFoundError:  # pragma: no cover
    system_site_packages = (
        f"/usr/local/lib/python{sys.version_info.major}."
        f"{sys.version_info.minor}/dist-packages"
    )
    if system_site_packages not in sys.path:
        sys.path.append(system_site_packages)
    from neomodel import db as neo4j_db

DEFAULT_STUDY_TYPE = "exome"
REPORT_TYPE = "nig_study_type_migration"
ROLLBACK_REPORT_TYPE = "nig_study_type_migration_rollback"


def _write_private(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def find_studies_without_type(graph: Any) -> List[Any]:
    return list(
        graph.Study.nodes.filter(study_type__isnull=True).all()
    )


def build_plan(graph: Any) -> Dict[str, Any]:
    studies = find_studies_without_type(graph)
    return {
        "report_type": "nig_study_type_migration_plan",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "default_study_type": DEFAULT_STUDY_TYPE,
        "read_only": True,
        "studies_to_migrate": sorted(str(s.uuid) for s in studies),
        "count": len(studies),
    }


def apply_migration(graph: Any, report_output: Path) -> Dict[str, Any]:
    touched: List[str] = []
    neo4j_db.begin()
    try:
        studies = find_studies_without_type(graph)
        for study in studies:
            study.study_type = DEFAULT_STUDY_TYPE
            study.save()
            touched.append(str(study.uuid))
            log.info("Study {} migrated to study_type={}", study.uuid, DEFAULT_STUDY_TYPE)

        report = {
            "report_type": REPORT_TYPE,
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "applied_study_type": DEFAULT_STUDY_TYPE,
            "studies": touched,
        }
        _write_private(report_output, report)
        neo4j_db.commit()
    except Exception:
        neo4j_db.rollback()
        raise

    return {
        "report_type": "nig_study_type_migration_result",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "changed_studies": len(touched),
        "report": str(report_output),
    }


def rollback_migration(graph: Any, report: Dict[str, Any]) -> Dict[str, Any]:
    if report.get("report_type") != REPORT_TYPE:
        raise ValueError("The supplied file is not a NIG study_type migration report")

    applied_type = report.get("applied_study_type")
    restored = 0
    skipped = 0
    neo4j_db.begin()
    try:
        for uuid in report.get("studies", []):
            study = graph.Study.nodes.get_or_none(uuid=uuid)
            if study is None:
                log.warning("Rollback: study {} no longer exists, skipping", uuid)
                skipped += 1
                continue
            if study.study_type != applied_type:
                log.warning(
                    "Rollback: study {} study_type was changed since migration "
                    "(current={}, expected={}), skipping",
                    uuid,
                    study.study_type,
                    applied_type,
                )
                skipped += 1
                continue
            study.study_type = None
            study.save()
            restored += 1
        neo4j_db.commit()
    except Exception:
        neo4j_db.rollback()
        raise

    return {
        "report_type": "nig_study_type_migration_rollback_result",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "restored_studies": restored,
        "skipped_studies": skipped,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--rollback", type=Path)
    parser.add_argument("--report", type=Path, help="Where to write the apply report")
    parser.add_argument("--output", type=Path, help="Where to write dry-run/rollback result")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    graph = neo4j.get_instance()

    if args.dry_run:
        result = build_plan(graph)
    elif args.apply:
        if args.report is None:
            raise SystemExit("--apply requires --report <path>")
        result = apply_migration(graph, args.report)
    else:
        result = rollback_migration(graph, _load_json(args.rollback))

    if args.output:
        _write_private(args.output, result)
        print(f"Report written to {args.output}")
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        log.error("Study type migration failed: {}", exc)
        sys.exit(1)
