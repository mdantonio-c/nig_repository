"""Resumable multi-chunk upload to Omics.

Implements the upload:
``/upload/start`` -> ``/upload/chunk`` (repeated) -> ``/upload/complete``,
with ``/upload/status`` and ``/upload/abort`` available for resume/cleanup.
"""

import base64
import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import requests

from nig.services.omics.errors import OmicsRequestError
from nig.services.omics.models import UploadSession

# Fallback only: the server's `recommended_chunk_size` from /upload/start is
# always preferred when present.
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
# A chunk is idempotent (same upload_id + chunk_number overwrites the part),
# so transient failures are retried; 4xx, auth and quota errors are not.
CHUNK_ATTEMPTS = 3
CHUNK_BACKOFF_SECONDS = 2.0
FASTQ_FILETYPE = "Fastq"


def chunk_checksum(chunk: bytes) -> str:
    """Base64-encoded SHA-256 of a single upload chunk (plan section 4.2)."""
    digest = hashlib.sha256(chunk).digest()
    return base64.b64encode(digest).decode("ascii")


class OmicsUploader:
    def __init__(
        self,
        request: Callable[..., Any],
        timeout: int,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # `request` is the authenticated, retrying request callable owned by
        # OmicsClient; the uploader itself knows nothing about auth/sessions.
        self._request = request
        self._timeout = timeout
        self._sleep = sleep

    def start(
        self,
        filename: str,
        file_size: int,
        tags: Optional[List[str]] = None,
        overwrite: bool = False,
    ) -> UploadSession:
        # NIG only uploads FASTQ inputs. The filetype selects the Omics graph
        # label: /tools/nig/germline rejects inputs not labelled Fastq (422).
        payload = {
            "filename": filename,
            "file_size": file_size,
            "overwrite": overwrite,
            "filetype": FASTQ_FILETYPE,
            "tags": tags or [],
        }
        response = self._request("POST", "/upload/start", json=payload)
        data = response.json()
        return UploadSession(
            upload_id=data["upload_id"],
            recommended_chunk_size=data.get(
                "recommended_chunk_size", DEFAULT_CHUNK_SIZE
            ),
            uploaded_parts=data.get("uploaded_parts", []),
            resuming=data.get("resuming", False),
        )

    def status(self, upload_id: str) -> Dict[str, Any]:
        response = self._request("GET", f"/upload/status/{upload_id}")
        return response.json()

    def abort(self, upload_id: str) -> None:
        self._request("DELETE", f"/upload/abort/{upload_id}")

    def complete(self, upload_id: str, tags: Optional[List[str]] = None) -> str:
        response = self._request(
            "POST",
            "/upload/complete",
            json={"upload_id": upload_id, "tags": tags or []},
        )
        data = response.json()
        return str(data["file_id"])

    def upload_file(
        self,
        path: Path,
        tags: Optional[List[str]] = None,
        remote_filename: Optional[str] = None,
    ) -> str:
        """Upload ``path``, resuming a previous session when Omics offers one.

        ``remote_filename`` must be unique per NIG dataset: Omics resumes by
        filename, so a shared basename could resume another file's session.
        Any failure after the session is opened aborts it (best effort): the
        caller never resumes a failed dataset upload, it starts a new one.
        """
        file_size = path.stat().st_size
        session = self.start(remote_filename or path.name, file_size, tags=tags)
        chunk_size = session.recommended_chunk_size or DEFAULT_CHUNK_SIZE

        try:
            already_uploaded: Set[int] = set()
            if session.resuming:
                already_uploaded = self._validated_parts(
                    session.uploaded_parts, file_size, chunk_size
                )

            with path.open("rb") as stream:
                chunk_number = 0
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    chunk_number += 1
                    if chunk_number in already_uploaded:
                        continue
                    self._upload_chunk(session.upload_id, chunk_number, chunk)

            return self.complete(session.upload_id, tags=tags)
        except Exception:
            # A partial upload never belongs to a later batch. Best-effort
            # abort is intentionally local to the uploader because it is the
            # only layer that still knows the server-side upload session id.
            try:
                self.abort(session.upload_id)
            except Exception:  # pragma: no cover - remote cleanup failure
                pass
            raise

    @staticmethod
    def _validated_parts(
        uploaded_parts: List[Dict[str, Any]], file_size: int, chunk_size: int
    ) -> Set[int]:
        """Accept a resumed session only if its parts match this local file."""
        total_chunks = max((file_size + chunk_size - 1) // chunk_size, 1)
        parts: Set[int] = set()
        for part in uploaded_parts:
            number = int(part["part_number"])
            if not 1 <= number <= total_chunks:
                raise OmicsRequestError("Resumed upload has an unexpected part number")
            expected = (
                chunk_size
                if number < total_chunks
                else file_size - chunk_size * (total_chunks - 1)
            )
            size = part.get("size")
            if size is not None and int(size) != expected:
                raise OmicsRequestError("Resumed upload does not match the local file")
            parts.add(number)
        return parts

    def _upload_chunk(self, upload_id: str, chunk_number: int, chunk: bytes) -> None:
        checksum = chunk_checksum(chunk)
        for attempt in range(1, CHUNK_ATTEMPTS + 1):
            try:
                self._request(
                    "POST",
                    "/upload/chunk",
                    data={
                        "upload_id": upload_id,
                        "chunk_number": chunk_number,
                        "checksum_SHA256": checksum,
                    },
                    files={"file": chunk},
                )
                return
            except (requests.ConnectionError, requests.Timeout, OmicsRequestError) as exc:
                if not self._retryable(exc) or attempt == CHUNK_ATTEMPTS:
                    raise
                self._sleep(CHUNK_BACKOFF_SECONDS * attempt)

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        if isinstance(exc, OmicsRequestError):
            return exc.status_code is not None and exc.status_code >= 500
        return True
