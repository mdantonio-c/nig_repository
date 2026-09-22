"""Resumable multi-chunk upload to Omics.

Implements the upload:
``/upload/start`` -> ``/upload/chunk`` (repeated) -> ``/upload/complete``,
with ``/upload/status`` and ``/upload/abort`` available for resume/cleanup.
"""

import base64
import hashlib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from nig.services.omics.models import UploadSession

# Fallback only: the server's `recommended_chunk_size` from /upload/start is
# always preferred when present.
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024


def chunk_checksum(chunk: bytes) -> str:
    """Base64-encoded SHA-256 of a single upload chunk (plan section 4.2)."""
    digest = hashlib.sha256(chunk).digest()
    return base64.b64encode(digest).decode("ascii")


class OmicsUploader:
    def __init__(self, request: Callable[..., Any], timeout: int) -> None:
        # `request` is the authenticated, retrying request callable owned by
        # OmicsClient; the uploader itself knows nothing about auth/sessions.
        self._request = request
        self._timeout = timeout

    def start(
        self,
        filename: str,
        file_size: int,
        tags: Optional[List[str]] = None,
        overwrite: bool = False,
    ) -> UploadSession:
        payload = {
            "filename": filename,
            "file_size": file_size,
            "overwrite": overwrite,
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

    def upload_file(self, path: Path, tags: Optional[List[str]] = None) -> str:
        file_size = path.stat().st_size
        session = self.start(path.name, file_size, tags=tags)
        chunk_size = session.recommended_chunk_size or DEFAULT_CHUNK_SIZE

        already_uploaded: Set[int] = set()
        if session.resuming:
            already_uploaded = {
                int(part["part_number"]) for part in session.uploaded_parts
            }

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

    def _upload_chunk(self, upload_id: str, chunk_number: int, chunk: bytes) -> None:
        checksum = chunk_checksum(chunk)
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
