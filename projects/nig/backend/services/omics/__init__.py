"""NIG <-> Omics REST client.

Public entry point: :class:`OmicsClient`.
"""

from nig.services.omics.client import OmicsClient
from nig.services.omics.errors import (
    OmicsAuthError,
    OmicsError,
    OmicsQuotaExceeded,
    OmicsRequestError,
)

__all__ = [
    "OmicsClient",
    "OmicsError",
    "OmicsAuthError",
    "OmicsQuotaExceeded",
    "OmicsRequestError",
]
