"""Unit tests for :mod:`nig.services.omics.uploader`.

The `request` callable used by :class:`OmicsUploader` is faked here (a
recording function returning canned :class:`FakeResponse` objects), so these
tests never touch the network.
"""

from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests

from nig.services.omics.errors import OmicsQuotaExceeded, OmicsRequestError
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

    def program(self, path: str, response: Any) -> None:
        self._responses.setdefault(path, []).append(response)

    def __call__(self, method: str, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, path, kwargs))
        queue = self._responses.get(path)
        if not queue:
            raise AssertionError(f"No programmed response for {method} {path}")
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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


def test_start_declares_fastq_filetype() -> None:
    request = FakeRequest()
    request.program("/upload/start", FakeResponse({"upload_id": "u1"}))

    OmicsUploader(request, timeout=30).start("sample_R1.fastq.gz", 2048)

    assert request.calls[0][2]["json"]["filetype"] == "Fastq"


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


def test_upload_file_aborts_the_session_when_quota_is_exceeded(tmp_path: Path) -> None:
    file_path = tmp_path.joinpath("sample.fastq.gz")
    file_path.write_bytes(b"A" * 10)
    request = FakeRequest()
    request.program(
        "/upload/start",
        FakeResponse({"upload_id": "u1", "recommended_chunk_size": 10}),
    )
    request.program("/upload/abort/u1", FakeResponse({}))
    uploader = OmicsUploader(request, timeout=30)

    def quota_error(*args: Any, **kwargs: Any) -> None:
        raise OmicsQuotaExceeded("Storage limit reached")

    uploader._upload_chunk = quota_error  # type: ignore[assignment]

    with pytest.raises(OmicsQuotaExceeded):
        uploader.upload_file(file_path)

    assert any(call[1] == "/upload/abort/u1" for call in request.calls)


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


def _single_chunk_upload(tmp_path: Path, size: int = 10) -> Any:
    file_path = tmp_path.joinpath("sample_R1.fastq.gz")
    file_path.write_bytes(b"A" * size)
    request = FakeRequest()
    request.program(
        "/upload/start",
        FakeResponse({"upload_id": "u1", "recommended_chunk_size": 10}),
    )
    sleeps: List[float] = []
    return file_path, request, OmicsUploader(request, timeout=30, sleep=sleeps.append), sleeps


def test_upload_uses_the_dataset_scoped_remote_filename(tmp_path: Path) -> None:
    file_path, request, uploader, _ = _single_chunk_upload(tmp_path)
    request.program("/upload/chunk", FakeResponse({}))
    request.program("/upload/complete", FakeResponse({"file_id": "f1"}))

    uploader.upload_file(file_path, remote_filename="d1_sample_R1.fastq.gz")

    start = request.calls[0][2]["json"]
    assert start["filename"] == "d1_sample_R1.fastq.gz"
    # never overwrite a remote file: collisions must fail, not replace data
    assert start["overwrite"] is False


@pytest.mark.parametrize(
    "transient",
    [
        requests.ConnectionError("reset"),
        requests.Timeout("slow"),
        OmicsRequestError("bad gateway", status_code=502),
    ],
)
def test_transient_chunk_errors_are_retried(tmp_path: Path, transient: Exception) -> None:
    file_path, request, uploader, sleeps = _single_chunk_upload(tmp_path)
    request.program("/upload/chunk", transient)
    request.program("/upload/chunk", FakeResponse({}))
    request.program("/upload/complete", FakeResponse({"file_id": "f1"}))

    assert uploader.upload_file(file_path) == "f1"
    assert len([c for c in request.calls if c[1] == "/upload/chunk"]) == 2
    assert sleeps == [2.0]


def test_client_chunk_errors_are_not_retried_and_abort(tmp_path: Path) -> None:
    file_path, request, uploader, sleeps = _single_chunk_upload(tmp_path)
    request.program("/upload/chunk", OmicsRequestError("bad checksum", status_code=400))
    request.program("/upload/abort/u1", FakeResponse({}))

    with pytest.raises(OmicsRequestError):
        uploader.upload_file(file_path)

    assert len([c for c in request.calls if c[1] == "/upload/chunk"]) == 1
    assert sleeps == []
    assert request.calls[-1][1] == "/upload/abort/u1"


def test_persistent_transient_errors_give_up_and_abort(tmp_path: Path) -> None:
    file_path, request, uploader, sleeps = _single_chunk_upload(tmp_path)
    for _ in range(3):
        request.program("/upload/chunk", requests.ConnectionError("down"))
    request.program("/upload/abort/u1", FakeResponse({}))

    with pytest.raises(requests.ConnectionError):
        uploader.upload_file(file_path)

    assert sleeps == [2.0, 4.0]
    assert request.calls[-1][1] == "/upload/abort/u1"


def test_generic_error_mid_upload_aborts_the_session(tmp_path: Path) -> None:
    file_path, request, uploader, _ = _single_chunk_upload(tmp_path)
    request.program("/upload/chunk", FakeResponse({}))
    request.program("/upload/complete", RuntimeError("unexpected"))
    request.program("/upload/abort/u1", FakeResponse({}))

    with pytest.raises(RuntimeError):
        uploader.upload_file(file_path)

    assert request.calls[-1][1] == "/upload/abort/u1"


@pytest.mark.parametrize(
    "parts",
    [
        [{"part_number": 3, "size": 10}],  # beyond the local file
        [{"part_number": 1, "size": 7}],  # size of a different file
        [{"part_number": 0}],
    ],
)
def test_resume_of_a_non_matching_session_is_rejected(
    tmp_path: Path, parts: List[Dict[str, Any]]
) -> None:
    file_path = tmp_path.joinpath("sample_R1.fastq.gz")
    file_path.write_bytes(b"A" * 20)
    request = FakeRequest()
    request.program(
        "/upload/start",
        FakeResponse(
            {
                "upload_id": "u1",
                "recommended_chunk_size": 10,
                "resuming": True,
                "uploaded_parts": parts,
            }
        ),
    )
    request.program("/upload/abort/u1", FakeResponse({}))

    with pytest.raises(OmicsRequestError):
        OmicsUploader(request, timeout=30).upload_file(file_path)

    assert not [c for c in request.calls if c[1] == "/upload/chunk"]
    assert request.calls[-1][1] == "/upload/abort/u1"
