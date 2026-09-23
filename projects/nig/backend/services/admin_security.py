"""Security audit and best-effort notifications for admin-user operations."""

from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, Iterable, Optional, Set, Tuple

import pytz
from flask import has_request_context, request
from restapi.connectors.smtp.notifications import send_notification
from restapi.services.authentication import BaseAuthentication
from restapi.utilities.logs import Events, log, save_event_log
from restapi.utilities.uuid import getUUID

from nig.services.admin_policy import SENSITIVE_FIELDS, STAFF_ROLE, snapshot_user

ALERT_INTERVAL = timedelta(minutes=5)
_ALERTS: Dict[Tuple[str, str, str], datetime] = {}
_ALERT_LOCK = Lock()


def _request_metadata() -> Tuple[str, str, str]:
    if not has_request_context():
        return "-", "admin-hierarchy-script", getUUID()
    correlation_id = (
        request.headers.get("X-Request-ID")
        or request.headers.get("X-Correlation-ID")
        or getUUID()
    )
    return BaseAuthentication.get_remote_ip(), request.path, correlation_id


def _safe_changed_fields(fields: Iterable[str]) -> Set[str]:
    return {str(field) for field in fields if str(field) not in SENSITIVE_FIELDS}


def audit_admin_action(
    *,
    actor: Optional[Any],
    target: Optional[Any],
    action: str,
    outcome: str,
    reason: str,
    changed_fields: Iterable[str] = (),
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
) -> None:
    """Write a redacted event to RAPyDo's restricted security event log."""

    ip, url, correlation_id = _request_metadata()
    safe_fields = sorted(_safe_changed_fields(changed_fields))
    before = before or {}
    after = after or {}
    safe_diff = {
        field: {"old": before.get(field), "new": after.get(field)}
        for field in safe_fields
        if field in before or field in after
    }
    payload = {
        "nig_action": action,
        "outcome": outcome,
        "reason": reason,
        "actor_uuid": str(getattr(actor, "uuid", "")),
        "target_email": str(getattr(target, "email", before.get("email", ""))),
        "changed_fields": safe_fields,
        "changes": safe_diff,
        "correlation_id": correlation_id,
    }
    save_event_log(
        event=Events.modify,
        # Keep hierarchy audit records separate from RAPyDo's resource event
        # stream.  The inherited endpoint already writes the canonical User
        # create/read/update/delete event; making this supplemental record a
        # User event would change consumers' ``last User event`` semantics.
        # The redacted target identity remains in ``payload.target_email``.
        target=None,
        payload=payload,
        user=actor,
        ip=ip,
        url=url,
    )


def _privileged_recipients(auth: Any) -> Set[str]:
    recipients: Set[str] = set()
    for user in auth.get_users():
        roles = set(auth.get_roles_from_user(user))
        if "admin_root" in roles or STAFF_ROLE in roles:
            email = str(getattr(user, "email", ""))
            if email:
                recipients.add(email)
    return recipients


def _send(address: str, data: Dict[str, Any], subject: str) -> None:
    try:
        sent = send_notification(
            subject=subject,
            template="admin_security_event.html",
            to_address=address,
            data=data,
        )
        if not sent:
            log.error("Admin security notification delivery failed")
    except Exception as exc:  # notification failures never roll back mutations
        log.error("Admin security notification raised {}", type(exc).__name__)


def notify_admin_action(
    *,
    auth: Any,
    actor: Any,
    target: Optional[Any],
    action: str,
    changed_fields: Iterable[str],
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
) -> None:
    """Notify affected users without including credentials or tokens."""

    fields = sorted(set(changed_fields))
    before = before if before is not None else {}
    after = (
        after
        if after is not None
        else (snapshot_user(target, auth) if target is not None else {})
    )
    data = {
        "action": action,
        "actor": str(getattr(actor, "email", "")),
        "target": after.get("email") or before.get("email", ""),
        "changed_fields": ", ".join(fields) or "none",
        "outcome": "completed",
        "timestamp": datetime.now(pytz.utc).isoformat(),
    }

    recipients: Set[str] = set()
    old_email = str(before.get("email", ""))
    new_email = str(after.get("email", ""))
    if old_email:
        recipients.add(old_email)
    if new_email:
        recipients.add(new_email)

    before_roles = set(before.get("roles", []))
    after_roles = set(after.get("roles", []))
    if STAFF_ROLE in before_roles.symmetric_difference(after_roles):
        recipients.update(_privileged_recipients(auth))

    for address in recipients:
        _send(address, data, "Administrative account update")


def notify_denied_admin_action(
    *,
    auth: Any,
    actor: Any,
    target: Optional[Any],
    action: str,
    reason: str,
) -> None:
    """Rate-limit high-severity denial alerts per process and operation."""

    actor_id = str(getattr(actor, "uuid", ""))
    target_id = str(getattr(target, "uuid", ""))
    key = (actor_id, target_id, action)
    now = datetime.now(pytz.utc)
    with _ALERT_LOCK:
        last = _ALERTS.get(key)
        if last is not None and now - last < ALERT_INTERVAL:
            return
        _ALERTS[key] = now

    data = {
        "action": action,
        "actor": str(getattr(actor, "email", "")),
        "target": str(getattr(target, "email", "")),
        "changed_fields": "not disclosed",
        "outcome": "denied",
        "reason": reason,
        "timestamp": now.isoformat(),
    }
    for address in _privileged_recipients(auth):
        _send(address, data, "Denied administrative operation")
