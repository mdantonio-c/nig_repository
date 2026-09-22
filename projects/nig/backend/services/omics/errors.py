"""Exceptions raised by the Omics client (issue #76).

Kept intentionally small and specific: callers (Celery tasks) branch on these
types to decide whether to retry, requeue a dataset (quota) or fail loudly.
"""

from typing import Any, Optional


class OmicsError(Exception):
    """Base class for all Omics client errors."""


class OmicsAuthError(OmicsError):
    """Authentication with Omics failed (login or token refresh)."""


class OmicsQuotaExceeded(OmicsError):
    """The Omics storage quota would be/was exceeded by this operation.

    Not fatal: the caller should requeue the affected dataset for a later
    batch (see the integration plan, section 6.4), never treat this as a
    permanent dataset error.
    """


class OmicsRequestError(OmicsError):
    """A non-2xx response was received from Omics (excluding auth/quota)."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        payload: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
