"""Report and conservatively reconcile remote Omics storage.

Report-only by design: remote objects are classified against Neo4j (the only
source of truth) and ``OMICS_ORPHAN_TTL_HOURS``, but nothing is deleted until
a retention policy is validated with Omics. The report never contains full
remote identifiers: only counts, bytes and truncated ids.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytz
from nig.services.omics.client import _obscure
from nig.services.omics.settings import client_from_env, omics_enabled
from restapi.connectors import neo4j
from restapi.connectors.celery import CeleryExt, Task
from restapi.env import Env
from restapi.utilities.logs import log

TERMINAL_DATASET_STATUSES = ("COMPLETED", "ERROR")
DEFAULT_ORPHAN_TTL_HOURS = 72
MAX_SAMPLE_IDS = 20
CATEGORIES = (
    # not in Neo4j and older than the TTL: candidates for the agreed cleanup
    "orphan_candidates",
    # not in Neo4j, but recent or without a parsable date: never eligible
    "unknown_recent",
    # registered, dataset terminal for more than the TTL: Omics cleanup not
    # observed, candidates for the registered-id fallback
    "cleanup_not_observed",
    # registered, dataset terminal but still within the TTL
    "terminal_recent",
    # registered and owned by a dataset still in progress
    "known_active",
)


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(pytz.utc)


def registered_remote_owners(graph: Any) -> Dict[str, Any]:
    """Map every remote filename persisted in Neo4j by NIG to its dataset.

    Keyed by ``user_filename``, not ``file_id``: Omics re-encrypts the id on
    every response, so an id saved at upload/fetch time can never be matched
    again in a later listing. The remote filename is dataset-uuid-prefixed
    (uploads) or stored verbatim (fetched artifacts), so it stays unique and
    stable across calls.
    """
    owners: Dict[str, Any] = {}
    for file_node in graph.File.nodes.filter(omics_file_id__isnull=False).all():
        dataset = file_node.dataset.single()
        if dataset is not None:
            owners[f"{dataset.uuid}_{file_node.name}"] = dataset
    for artifact in graph.OmicsArtifact.nodes.filter(remote_file_id__isnull=False).all():
        if artifact.name:
            owners[str(artifact.name)] = artifact.dataset.single()
    return owners


def registered_remote_names(graph: Any) -> set:
    """Return only the remote filenames already persisted in Neo4j by NIG itself."""
    return set(registered_remote_owners(graph))


def _remote_date(item: Dict[str, Any]) -> Optional[datetime]:
    value = item.get("date")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=pytz.utc)


def _classify(
    item: Dict[str, Any], owners: Dict[str, Any], threshold: datetime
) -> str:
    filename = str(item.get("user_filename") or "")
    if not filename or filename not in owners:
        created = _remote_date(item)
        if created is not None and created < threshold:
            return "orphan_candidates"
        return "unknown_recent"
    dataset = owners[filename]
    if dataset is None or dataset.status in TERMINAL_DATASET_STATUSES:
        last_update = getattr(dataset, "status_update", None)
        if last_update is None or last_update < threshold:
            return "cleanup_not_observed"
        return "terminal_recent"
    return "known_active"


def _summary(entries: Iterable[Tuple[str, int]]) -> Dict[str, Any]:
    entries = list(entries)
    return {
        "count": len(entries),
        "bytes": sum(size for _, size in entries),
        "sample_ids": [_obscure(remote_id) for remote_id, _ in entries[:MAX_SAMPLE_IDS]],
    }


def reconcile(
    graph: Any,
    client: Any,
    delete: bool = False,
    orphan_ttl_hours: int = DEFAULT_ORPHAN_TTL_HOURS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Classify remote storage against graph state, without deleting anything.

    A later, explicit deletion policy must prove that an object is both
    NIG-owned and eligible under the agreed remote-retention/TTL contract.
    """
    timestamp = _now(now)
    threshold = timestamp - timedelta(hours=orphan_ttl_hours)
    owners = registered_remote_owners(graph)
    grouped: Dict[str, List[Tuple[str, int]]] = {name: [] for name in CATEGORIES}
    for item in client.list_uploaded_files():
        if not isinstance(item, dict) or not item.get("file_id"):
            continue
        category = _classify(item, owners, threshold)
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        grouped[category].append((str(item["file_id"]), size))

    if delete:
        log.warning(
            "OMICS_CLEANUP_DELETE is requested but cleanup is report-only "
            "until the retention policy is validated"
        )
    usage = client.get_storage_usage()
    return {
        "generated_at": timestamp.isoformat(),
        "orphan_ttl_hours": orphan_ttl_hours,
        "remote_count": sum(len(entries) for entries in grouped.values()),
        "categories": {name: _summary(grouped[name]) for name in CATEGORIES},
        "deleted": 0,
        "delete_requested": bool(delete),
        "storage": {
            "usage": usage.usage,
            "quota": usage.quota,
            "limit": usage.limit,
            "can_upload": usage.can_upload,
        },
    }


@CeleryExt.task(idempotent=True, autoretry_for=(ConnectionResetError,))
def omics_cleanup(self: Task[[], None]) -> None:
    if not omics_enabled():
        log.warning("OMICS_ENABLE is off, Omics cleanup not executed")
        return
    report = reconcile(
        neo4j.get_instance(),
        client_from_env(),
        delete=Env.get_bool("OMICS_CLEANUP_DELETE", False),
        orphan_ttl_hours=Env.get_int("OMICS_ORPHAN_TTL_HOURS", DEFAULT_ORPHAN_TTL_HOURS),
    )
    categories = report["categories"]
    if categories["orphan_candidates"]["count"] or categories["cleanup_not_observed"]["count"]:
        log.warning(
            "Omics storage needs attention: {} orphan candidates, {} registered "
            "objects whose cleanup was not observed",
            categories["orphan_candidates"]["count"],
            categories["cleanup_not_observed"]["count"],
        )
    log.info("Omics cleanup report: {}", report)
