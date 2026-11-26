"""Runtime settings shared by every Omics Celery task.

``OMICS_ENABLE`` guards every entry point, not only the dispatcher: a task
sent manually (or left in the broker queue) while the integration is disabled
must not contact Omics nor change the graph.
"""

from restapi.env import Env

from nig.services.omics.client import OmicsClient
from nig.services.omics.planner import DEFAULT_MAX_FASTQ_BYTES

# Generic, user-facing messages. Technical details (remote errors, paths,
# identifiers) only go to ``Dataset.omics_error_message`` and to the logs.
USER_ANALYSIS_ERROR = (
    "The analysis could not be completed. The NIG administrators have been notified."
)
USER_DATASET_TOO_LARGE = "The dataset is too large to be analysed."
DEFAULT_MAX_DOWNLOAD_BYTES = 500_000_000_000


def max_fastq_bytes_from_env() -> int:
    """Fail closed on invalid limits; Env.get_int silently falls back."""
    raw = Env.get("OMICS_MAX_FASTQ_BYTES", str(DEFAULT_MAX_FASTQ_BYTES))
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        raise ValueError("OMICS_MAX_FASTQ_BYTES must be a positive integer") from None
    if limit <= 0:
        raise ValueError("OMICS_MAX_FASTQ_BYTES must be a positive integer")
    return limit


def fastq_limit_error(size_bytes: int, limit: int) -> str:
    return (
        f"Dataset FASTQ size {size_bytes} bytes exceeds "
        f"OMICS_MAX_FASTQ_BYTES ({limit} bytes)"
    )


def omics_enabled() -> bool:
    return Env.get_bool("OMICS_ENABLE", False)


def client_from_env() -> OmicsClient:
    return OmicsClient(
        Env.get("OMICS_API_URL", ""),
        Env.get("OMICS_USERNAME", ""),
        Env.get("OMICS_PASSWORD", ""),
        timeout=Env.get_int("OMICS_REQUEST_TIMEOUT", 60),
        max_download_bytes=Env.get_int(
            "OMICS_MAX_DOWNLOAD_BYTES", DEFAULT_MAX_DOWNLOAD_BYTES
        ),
    )
