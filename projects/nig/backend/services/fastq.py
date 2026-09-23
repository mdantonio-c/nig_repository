"""Shared FASTQ filename validation used by upload and pipeline dispatchers."""

import re
from typing import Optional, Tuple

# A dataset contains one single-end R1 file, or a paired R1/R2 pair with the
# same sample name. Keep this expression in one place: input validation and
# every pipeline launcher must apply the exact same contract.
FASTQ_FILENAME_PATTERN = re.compile(r"^([a-zA-Z0-9_-]+)_(R[12])\.fastq\.gz$")


def parse_fastq_filename(filename: str) -> Optional[Tuple[str, str]]:
    """Return ``(sample_name, R1|R2)`` when *filename* is a valid FASTQ name."""
    match = FASTQ_FILENAME_PATTERN.match(filename)
    if match is None:
        return None
    return match.group(1), match.group(2)
