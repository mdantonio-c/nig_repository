"""Unit tests for :mod:`nig.services.omics.uploader`.

The `request` callable used by :class:`OmicsUploader` is faked here (a
recording function returning canned :class:`FakeResponse` objects), so these
tests never touch the network.
"""

from pathlib import Path
from typing import Any, Dict, List

import pytest

from nig.services.omics.uploader import DEFAULT_CHUNK_SIZE, OmicsUploader, chunk_checksum


class FakeResponse:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


class FakeRequest:
    """Records calls and returns pre-programmed responses per path."""

    def __init__(self) -> None:
        self.calls: List[Any] = []
        self._responses: Dict[str, List[FakeResponse]] = {}

    def program(self, path: str, response: FakeResponse) -> None:
        self._responses.setdefault(path, []).append(response)

    def __call__(self, method: str, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, path, kwargs))
        queue = self._responses.get(path)
        if not queue:
            raise AssertionError(f"No programmed response for {method} {path}")
        return queue.pop(0)


def test_start_returns_upload_session_with_defaults() -> None:
    request = FakeRequest()
    request.program(
        "/upload/start",
        FakeResponse({"upload_id": "u1", "recommended_chunk_size": 1024}),
    )
    uploader = OmicsUploader(request, timeout=30)

    session = uploader.start("sample_R1.fastq.gz", 2048)

    assert session.upload_id == "u1"
    assert session.recommended_chunk_size == 1024
    assert session.resuming is False
    assert session.uploaded_parts == []


def test_start_falls_back_to_default_chunk_size_when_missing() -> None:
    request = FakeRequest()
    request.program("/upload/start", FakeResponse({"upload_id": "u1"}))
    uploader = OmicsUploader(request, timeout=30)

    session = uploader.start("f.fastq.gz", 10)

    assert session.recommended_chunk_size == DEFAULT_CHUNK_SIZE


def test_chunk_checksum_is_stable_base64_sha256() -> None:
    checksum_a = chunk_checksum(b"hello")
    checksum_b = chunk_checksum(b"hello")
    checksum_c = chunk_checksum(b"world")

    assert checksum_a == checksum_b
    assert checksum_a != checksum_c
    # SHA-256 digest is 32 bytes -> 44 base64 chars (with padding)
    assert len(checksum_a) == 44


def test_upload_file_sends_all_chunks_and_completes(tmp_path: Path) -> None:
    content = b"A" * 25  # 3 chunks of size 10 with a small chunk size
    file_path = tmp_path.joinpath("sample.fastq.gz")
    file_path.write_bytes(content)

    request = FakeRequest()
    request.program(
        "/upload/start",
        FakeResponse({"upload_id": "u1", "recommended_chunk_size": 10}),
    )
    for _ in range(3):
        request.program("/upload/chunk", FakeResponse({"part_number": 1, "etag": "e"}))
    request.program("/upload/complete", FakeResponse({"file_id": "f1"}))

    uploader = OmicsUploader(request, timeout=30)
    file_id = uploader.upload_file(file_path, tags=["fastq"])

    assert file_id == "f1"
    chunk_calls = [c for c in request.calls if c[1] == "/upload/chunk"]
    assert len(chunk_calls) == 3
    # chunk_number increments and checksum is present on every call
    chunk_numbers = [c[2]["data"]["chunk_number"] for c in chunk_calls]
    assert chunk_numbers == [1, 2, 3]
    for call in chunk_calls:
        assert "checksum_SHA256" in call[2]["data"]
        assert "file" in call[2]["files"]


def test_upload_file_resume_skips_already_uploaded_parts(tmp_path: Path) -> None:
    content = b"A" * 20  # 2 chunks of size 10
    file_path = tmp_path.joinpath("sample.fastq.gz")
    file_path.write_bytes(content)

    request = FakeRequest()
    request.program(
        "/upload/start",
        FakeResponse(
            {
                "upload_id": "u1",
                "recommended_chunk_size": 10,
                "resuming": True,
                "uploaded_parts": [{"part_number": 1, "size": 10, "etag": "e1"}],
            }
        ),
    )
    request.program("/upload/chunk", FakeResponse({"part_number": 2, "etag": "e2"}))
    request.program("/upload/complete", FakeResponse({"file_id": "f1"}))

    uploader = OmicsUploader(request, timeout=30)
    file_id = uploader.upload_file(file_path)

    assert file_id == "f1"
    chunk_calls = [c for c in request.calls if c[1] == "/upload/chunk"]
    assert len(chunk_calls) == 1
    assert chunk_calls[0][2]["data"]["chunk_number"] == 2


def test_abort_calls_delete_endpoint() -> None:
    request = FakeRequest()
    request.program("/upload/abort/u1", FakeResponse({}))
    uploader = OmicsUploader(request, timeout=30)

    uploader.abort("u1")

    assert request.calls[0][0] == "DELETE"
    assert request.calls[0][1] == "/upload/abort/u1"


def test_status_calls_status_endpoint() -> None:
    request = FakeRequest()
    request.program(
        "/upload/status/u1",
        FakeResponse({"upload_id": "u1", "filename": "f", "uploaded_parts": []}),
    )
    uploader = OmicsUploader(request, timeout=30)

    status = uploader.status("u1")

    assert status["upload_id"] == "u1"
    assert request.calls[0][0] == "GET"
