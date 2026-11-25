#!/usr/bin/env python3
"""Read-only consistency check between Neo4j and the expected Omics state.

Neo4j is the only source of truth for the Omics integration: no
new identifiers/paths are stored anywhere else. This script never mutates the
graph; it only reports inconsistencies that a human/operator should
investigate, for example:

* a ``Dataset`` with an ``omics_task_id`` but none of its ``File``s carry an
  ``omics_file_id`` (submitted without a tracked upload);
* an ``OmicsArtifact`` with no linked ``Dataset`` (orphan output);
* an ``OmicsArtifact`` marked ``DOWNLOADED`` without a ``local_path``.

Run via ``rapydo shell backend "python3 /code/nig/scripts/check_omics_state.py"``.
"""

import argparse
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from restapi.connectors import neo4j
from restapi.utilities.logs import log

REPORT_TYPE = "nig_omics_state_check"


def find_datasets_with_task_but_no_uploaded_file(graph: Any) -> List[str]:
    offenders = []
    datasets = graph.Dataset.nodes.filter(omics_task_id__isnull=False).all()
    for dataset in datasets:
        files = dataset.files.all()
        if not any(getattr(f, "omics_file_id", None) for f in files):
            offenders.append(str(dataset.uuid))
    return offenders


def find_artifacts_without_dataset(graph: Any) -> List[str]:
    offenders = []
    for artifact in graph.OmicsArtifact.nodes.all():
        if artifact.dataset.single() is None:
            offenders.append(str(artifact.uuid))
    return offenders


def find_downloaded_artifacts_without_local_path(graph: Any) -> List[str]:
    offenders = []
    for artifact in graph.OmicsArtifact.nodes.all():
        if artifact.status == "DOWNLOADED" and not artifact.local_path:
            offenders.append(str(artifact.uuid))
    return offenders


def find_inconsistencies(graph: Any) -> Dict[str, List[str]]:
    return {
        "dataset_with_task_no_uploaded_file": find_datasets_with_task_but_no_uploaded_file(
            graph
        ),
        "artifact_without_dataset": find_artifacts_without_dataset(graph),
        "artifact_downloaded_without_local_path": find_downloaded_artifacts_without_local_path(
            graph
        ),
    }


def build_report(graph: Any) -> Dict[str, Any]:
    issues = find_inconsistencies(graph)
    total_issues = sum(len(v) for v in issues.values())
    return {
        "report_type": REPORT_TYPE,
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "issues": issues,
        "total_issues": total_issues,
    }


def parse_args(argv: Any = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


def main() -> None:
    parse_args()

    graph = neo4j.get_instance()
    report = build_report(graph)

    if report["total_issues"]:
        log.warning(
            "Found {} Omics state inconsistencies: {}",
            report["total_issues"],
            report["issues"],
        )
    else:
        log.info("No Omics state inconsistencies found")

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
