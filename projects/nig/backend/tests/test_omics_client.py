"""Unit tests for :mod:`nig.services.omics.client`.

A fake ``requests``-like session (only ``.post()`` and ``.request()``) is
injected into :class:`OmicsClient`, so these tests never touch the network
and do not depend on the ``responses``/``requests_mock`` packages (not
available in this environment).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from nig.services.omics.client import OmicsClient
from nig.services.omics.errors import (
    OmicsAuthError,
    OmicsQuotaExceeded,
    OmicsRequestError,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: Optional[Dict[str, Any]] = None,
        content_chunks: Optional[List[bytes]] = None,
    ) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload or {}
        self._content_chunks = content_chunks or []
        # Mimics requests.Response.content: empty for a 204/no-body response,
        # non-empty whenever a JSON payload was provided.
        self.content = b"{}" if payload else b""

    def json(self) -> Dict[str, Any]:
        return self._payload

    def iter_content(self, chunk_size: int = 1):
        yield from self._content_chunks


class FakeSession:
    def __init__(self) -> None:
        self.post_queue: List[FakeResponse] = []
        self.request_queue: List[FakeResponse] = []
        self.calls: List[Any] = []

    def post(self, url: str, json: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append(("POST-auth", url, json))
        return self.post_queue.pop(0)

    def request(
        self, method: str, url: str, headers=None, timeout=None, verify=None, **kwargs
    ) -> FakeResponse:
        self.calls.append((method, url, headers, kwargs))
        return self.request_queue.pop(0)


def _client(session: FakeSession) -> OmicsClient:
    return OmicsClient(
        base_url="https://omics.dev.cineca.it/api/v1/",
        username="nig-service",
        password="s3cr3t",
        timeout=10,
        session=session,
    )


def _logged_in_session() -> FakeSession:
    session = FakeSession()
    session.post_queue.append(
        FakeResponse(200, {"access_token": "AT1", "refresh_token": "RT1"})
    )
    return session


def test_authenticate_performs_login() -> None:
    session = _logged_in_session()
    client = _client(session)

    client.authenticate()

    assert session.calls[0][0] == "POST-auth"


def test_request_refreshes_token_on_401_and_retries_successfully() -> None:
    session = _logged_in_session()
    session.post_queue.append(
        FakeResponse(200, {"access_token": "AT2", "refresh_token": "RT2"})
    )
    session.request_queue.append(FakeResponse(401))
    session.request_queue.append(
        FakeResponse(200, {"usage": 1, "quota": 100, "limit": 0.01})
    )

    client = _client(session)
    usage = client.get_storage_usage()

    assert usage.usage == 1
    # two `.request` calls: first got 401, second (after refresh) succeeded
    request_calls = [c for c in session.calls if c[0] != "POST-auth"]
    assert len(request_calls) == 2
    # the retried call carries the refreshed token
    assert request_calls[1][2]["Authorization"] == "Bearer AT2"


def test_quota_exceeded_403_with_matching_detail_raises_omics_quota_exceeded() -> None:
    session = _logged_in_session()
    session.request_queue.append(
        FakeResponse(403, {"detail": "Storage limit reached"})
    )
    client = _client(session)

    with pytest.raises(OmicsQuotaExceeded):
        client.get_storage_usage()


def test_403_without_quota_detail_raises_omics_request_error() -> None:
    session = _logged_in_session()
    session.request_queue.append(FakeResponse(403, {"detail": "Forbidden"}))
    client = _client(session)

    with pytest.raises(OmicsRequestError):
        client.get_storage_usage()


def test_persistent_401_raises_omics_auth_error() -> None:
    session = _logged_in_session()
    session.post_queue.append(
        FakeResponse(200, {"access_token": "AT2", "refresh_token": "RT2"})
    )
    session.request_queue.append(FakeResponse(401))
    session.request_queue.append(FakeResponse(401))
    client = _client(session)

    with pytest.raises(OmicsAuthError):
        client.get_storage_usage()


def test_other_error_status_raises_omics_request_error() -> None:
    session = _logged_in_session()
    session.request_queue.append(FakeResponse(500))
    client = _client(session)

    with pytest.raises(OmicsRequestError):
        client.get_storage_usage()


def test_get_storage_usage_maps_fields() -> None:
    session = _logged_in_session()
    session.request_queue.append(
        FakeResponse(200, {"usage": 10, "quota": 1000, "limit": 0.01, "can_upload": True})
    )
    client = _client(session)

    usage = client.get_storage_usage()

    assert (usage.usage, usage.quota, usage.limit, usage.can_upload) == (
        10,
        1000,
        0.01,
        True,
    )


def test_list_uploaded_files_returns_json_list() -> None:
    session = _logged_in_session()
    response = FakeResponse(200)
    response._payload = [{"file_id": "f1"}]
    response.content = b'[{"file_id": "f1"}]'
    session.request_queue.append(response)
    client = _client(session)

    files = client.list_uploaded_files()

    assert files == [{"file_id": "f1"}]


def test_list_uploaded_files_returns_empty_list_on_204_no_content() -> None:
    # Confirmed against the real Omics dev2 environment: an account with no
    # uploaded files gets a 204 with an empty body, not 200 + [].
    session = _logged_in_session()
    session.request_queue.append(FakeResponse(204))
    client = _client(session)

    files = client.list_uploaded_files()

    assert files == []


@pytest.mark.parametrize("input_files", [[], ["a", "b", "c"]])
def test_submit_nig_germline_rejects_invalid_input_count(
    input_files: List[str],
) -> None:
    session = _logged_in_session()
    client = _client(session)

    with pytest.raises(ValueError):
        client.submit_nig_germline(input_files, output_vcf="sample.g.vcf.gz")


@pytest.mark.parametrize("input_files", [["r1"], ["r1", "r2"]])
def test_submit_nig_germline_accepts_one_or_two_inputs(
    input_files: List[str],
) -> None:
    session = _logged_in_session()
    session.request_queue.append(
        FakeResponse(200, {"task_id": "t1", "status": "Received"})
    )
    client = _client(session)

    result = client.submit_nig_germline(input_files, output_vcf="sample.g.vcf.gz")

    assert result == {"task_id": "t1", "status": "Received"}
    _, url, _, kwargs = [c for c in session.calls if c[0] != "POST-auth"][0]
    assert url.endswith("/tools/nig/germline")
    assert kwargs["json"]["input_files"] == input_files
    assert kwargs["json"]["reference"] == "hg38"


def test_get_task_returns_task_info() -> None:
    session = _logged_in_session()
    session.request_queue.append(
        FakeResponse(
            200,
            {
                "task_id": "t1",
                "status": "Processing",
                "start": "2026-09-22T00:00:00Z",
            },
        )
    )
    client = _client(session)

    task = client.get_task("t1")

    assert task.task_id == "t1"
    assert task.status == "Processing"


def test_get_task_files_flattens_nested_wrapper_and_tags_kind() -> None:
    session = _logged_in_session()
    session.request_queue.append(
        FakeResponse(
            200,
            {
                "files": {
                    "gvcf": {"file_id": "f1", "user_filename": "s.g.vcf.gz"},
                    "tbi": {"file_id": "f2", "user_filename": "s.g.vcf.gz.tbi"},
                }
            },
        )
    )
    client = _client(session)

    files = client.get_task_files("t1")

    kinds = {f["_kind"] for f in files}
    assert kinds == {"gvcf", "tbi"}
    assert any(f["file_id"] == "f1" for f in files)


def test_get_task_files_ignores_unknown_shapes_without_crashing() -> None:
    session = _logged_in_session()
    session.request_queue.append(
        FakeResponse(200, {"files": {"bam": {"file_id": "f3"}, "weird": "unexpected"}})
    )
    client = _client(session)

    files = client.get_task_files("t1")

    assert [f["file_id"] for f in files] == ["f3"]


def test_delete_file_returns_true_on_success() -> None:
    session = _logged_in_session()
    session.request_queue.append(FakeResponse(200))
    client = _client(session)

    assert client.delete_file("f1") is True


def test_download_file_streams_to_part_then_renames(tmp_path: Path) -> None:
    session = _logged_in_session()
    session.request_queue.append(
        FakeResponse(200, content_chunks=[b"abc", b"def"])
    )
    client = _client(session)
    destination = tmp_path.joinpath("sample.g.vcf.gz")

    result = client.download_file("f1", destination)

    assert result == destination
    assert destination.read_bytes() == b"abcdef"
    assert not destination.with_name(destination.name + ".part").exists()


def test_download_file_rejects_wrong_size_and_removes_partial_file(tmp_path: Path) -> None:
    session = _logged_in_session()
    session.request_queue.append(FakeResponse(200, content_chunks=[b"abc"]))
    client = _client(session)
    destination = tmp_path.joinpath("sample.g.vcf.gz")

    with pytest.raises(OmicsRequestError):
        client.download_file("f1", destination, expected_size=4)

    assert not destination.exists()
    assert not destination.with_name(destination.name + ".part").exists()
