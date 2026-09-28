"""Isolated, testable Omics REST client.

Design constraints:

* every call has an explicit timeout;
* TLS verification is always on, never disabled, not even in dev;
* the access token is refreshed transparently on a single 401 retry;
* retry/backoff on 5xx and network errors, mirroring the reference CLI;
* no secret (password, token) and no full remote id is ever logged;
* ``OMICS_API_URL`` is deployment configuration, never a request parameter
  (no SSRF surface);
* :meth:`OmicsClient.delete_file` is a fallback only: the caller is
  responsible for only ever passing ``file_id`` values it has registered in
  its own graph.
"""

import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from restapi.utilities.logs import log

from nig.services.omics.auth import OmicsAuth
from nig.services.omics.errors import (
    OmicsAuthError,
    OmicsQuotaExceeded,
    OmicsRequestError,
)
from nig.services.omics.models import StorageUsage, TaskInfo
from nig.services.omics.uploader import OmicsUploader

DEFAULT_TIMEOUT = 60
# A quota-exceeded condition is HTTP 403 "Storage limit reached"; MMF's error
# handler returns it as {"message": ...} (plain FastAPI would use "detail").
QUOTA_STATUS_CODE = 403
QUOTA_DETAIL_MARKER = "storage limit reached"
# Free space always left on the local filesystem after a download.
MIN_FREE_DISK_BYTES = 1024**3


def _obscure(identifier: str) -> str:
    """Truncate an id for logging, never print it in full."""
    if len(identifier) <= 8:
        return "***"
    return f"{identifier[:4]}...{identifier[-4:]}"


# long opaque tokens (encrypted file ids, task ids) inside server messages
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9_\-=:.]{16,}")
MAX_DETAIL_LENGTH = 300


def _body_message(response: requests.Response) -> str:
    """Top-level server message: MMF ``message`` or plain FastAPI ``detail``."""
    try:
        body = response.json()
        message = body.get("message") or body.get("detail")
    except (ValueError, AttributeError):
        return ""
    return message if isinstance(message, str) else ""


def _hide_ids(text: str) -> str:
    return _OPAQUE_TOKEN.sub(lambda match: _obscure(match.group(0)), text)


def _error_detail(response: requests.Response) -> str:
    """Short, sanitized server explanation of a 4xx.

    Omics (MMF) answers ``{"message", "code", "request_id", "errors":
    [{"field", "message"}]}``; plain FastAPI answers ``{"detail": ...}``.
    Only field names and messages are kept (never echoed inputs), and opaque
    ids are obscured.
    """
    try:
        body = response.json()
        detail = body.get("detail")
    except (ValueError, AttributeError):
        return ""
    if detail is None and isinstance(body.get("message"), str):
        parts = [_hide_ids(body["message"])]
        errors = body.get("errors")
        for item in errors[:3] if isinstance(errors, list) else []:
            if isinstance(item, dict):
                field = str(item.get("field", ""))
                msg = _hide_ids(str(item.get("message", "")))
                parts.append(f"{field}: {msg}".strip(": "))
        return "; ".join(parts)[:MAX_DETAIL_LENGTH]
    if isinstance(detail, list):
        parts = []
        for item in detail[:3]:
            if isinstance(item, dict):
                loc = ".".join(str(part) for part in item.get("loc") or [])
                msg = _hide_ids(str(item.get("msg", "")))
                parts.append(f"{loc}: {msg}".strip(": "))
        text = "; ".join(parts)
    elif detail is None:
        return ""
    else:
        text = _hide_ids(str(detail))
    return text[:MAX_DETAIL_LENGTH]


class OmicsClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: int = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
        max_download_bytes: Optional[int] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_download_bytes = max_download_bytes
        self._session = session or self._build_session(max_retries)
        self._auth = OmicsAuth(
            self._session, self._base_url, username, password, timeout
        )
        self._uploader = OmicsUploader(self._request, timeout)

    @staticmethod
    def _build_session(max_retries: int) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=max_retries,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    # -- auth ---------------------------------------------------------------
    def authenticate(self) -> None:
        self._auth.login()

    # -- low level request with transparent 401 refresh ----------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self._base_url}/{path.lstrip('/')}"
        timeout = kwargs.pop("timeout", self._timeout)
        headers = dict(kwargs.pop("headers", None) or {})
        headers.update(self._auth.auth_header())

        response = self._session.request(
            method, url, headers=headers, timeout=timeout, verify=True, **kwargs
        )

        if response.status_code == 401:
            log.info("Omics access token expired, refreshing")
            self._auth.refresh()
            headers.update(self._auth.auth_header())
            response = self._session.request(
                method, url, headers=headers, timeout=timeout, verify=True, **kwargs
            )

        self._raise_for_status(response)
        return response

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.ok:
            return
        if response.status_code == 401:
            raise OmicsAuthError("Omics authentication failed (401 after refresh)")
        if response.status_code == QUOTA_STATUS_CODE:
            detail = _body_message(response)
            if QUOTA_DETAIL_MARKER in detail.lower():
                raise OmicsQuotaExceeded(
                    f"Omics storage quota exceeded (status {response.status_code}: "
                    f"{detail})"
                )
        detail = _error_detail(response) if 400 <= response.status_code < 500 else ""
        raise OmicsRequestError(
            f"Omics request failed with status {response.status_code}"
            + (f": {detail}" if detail else ""),
            status_code=response.status_code,
        )

    # -- storage --------------------------------------------------------------
    def get_storage_usage(self) -> StorageUsage:
        response = self._request("GET", "/storage/objects/usage")
        data = response.json()
        return StorageUsage(
            usage=data["usage"],
            quota=data["quota"],
            limit=data["limit"],
            can_upload=data.get("can_upload", True),
        )

    def list_uploaded_files(self) -> List[Dict[str, Any]]:
        response = self._request("GET", "/files/uploaded")
        # Omics returns 204 No Content (empty body) when the account has no
        # uploaded files, instead of 200 with an empty JSON list.
        if response.status_code == 204 or not response.content:
            return []
        # FileListResponse: {"files": [FileResponse, ...]} (OpenAPI spec,
        # confirmed live). An unknown shape must not look like an empty
        # listing: callers would then consider remote files already removed.
        payload = response.json()
        files = payload.get("files") if isinstance(payload, dict) else None
        if not isinstance(files, list):
            raise OmicsRequestError(
                "Unexpected Omics uploaded files payload",
                status_code=response.status_code,
            )
        return [item for item in files if isinstance(item, dict)]

    def delete_file(self, file_id: str) -> bool:
        # Fallback cleanup path only: the caller must
        # only pass ids already registered in NIG's own graph.
        response = self._request("DELETE", f"/storage/objects/{file_id}")
        return response.ok

    def download_file(
        self,
        file_id: str,
        destination: Path,
        expected_size: Optional[int] = None,
    ) -> Path:
        """Stream one object to ``destination`` through a ``.part`` file.

        The final name only appears after the whole body has been received
        and its size verified; any failure removes the partial file.
        """
        limit = self._max_download_bytes
        if expected_size is not None:
            if expected_size < 0:
                raise OmicsRequestError("Omics download has an invalid size")
            if limit is not None and expected_size > limit:
                raise OmicsRequestError(
                    "Omics download exceeds the configured size limit"
                )
            self.ensure_free_space(destination.parent, expected_size)
            limit = expected_size

        tmp_path = destination.with_name(destination.name + ".part")
        response: Optional[requests.Response] = None
        try:
            response = self._request(
                "GET", f"/storage/objects/download/{file_id}", stream=True
            )
            downloaded = 0
            with tmp_path.open("wb") as stream:
                for block in response.iter_content(chunk_size=1024 * 1024):
                    if not block:
                        continue
                    downloaded += len(block)
                    if limit is not None and downloaded > limit:
                        raise OmicsRequestError(
                            "Omics download is larger than expected"
                        )
                    stream.write(block)
            if expected_size is not None and downloaded != expected_size:
                raise OmicsRequestError(
                    "Omics download has an unexpected size: "
                    f"expected {expected_size}, received {downloaded}"
                )
            tmp_path.replace(destination)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        return destination

    @staticmethod
    def ensure_free_space(directory: Path, required_bytes: int) -> None:
        free = shutil.disk_usage(directory).free
        if free < required_bytes + MIN_FREE_DISK_BYTES:
            raise OmicsRequestError(
                "Not enough local disk space for the Omics download: "
                f"required {required_bytes} bytes, free {free} bytes"
            )

    # -- upload ---------------------------------------------------------------
    def upload_file(
        self,
        path: Path,
        tags: Optional[List[str]] = None,
        remote_filename: Optional[str] = None,
    ) -> str:
        file_id = self._uploader.upload_file(
            path, tags=tags, remote_filename=remote_filename
        )
        log.info(
            "Uploaded {} to Omics as file_id={}", path.name, _obscure(file_id)
        )
        return file_id

    def abort_upload(self, upload_id: str) -> None:
        self._uploader.abort(upload_id)

    # -- tools/tasks ------------------------------------------------------------
    def submit_nig_germline(
        self,
        input_file_ids: List[str],
        output_vcf: str,
        reference: str = "hg38",
    ) -> Dict[str, str]:
        if not 1 <= len(input_file_ids) <= 2:
            raise ValueError(
                "input_files must contain 1 (single-end) or 2 (R1, R2) file ids"
            )
        payload = {
            "input_files": input_file_ids,
            "reference": reference,
            "output_vcf": output_vcf,
        }
        response = self._request("POST", "/tools/nig/germline", json=payload)
        return response.json()

    def get_task(self, task_id: str) -> TaskInfo:
        response = self._request("GET", f"/tasks/{task_id}/")
        data = response.json()
        return TaskInfo(
            task_id=data["task_id"],
            status=data["status"],
            start=data.get("start"),
            end=data.get("end"),
            elapsed_time=data.get("elapsed_time"),
            parameters=data.get("parameters"),
        )

    def get_task_files(self, task_id: str) -> List[Dict[str, Any]]:
        """Flatten the nested ``/files/proc/{task_id}`` output wrapper.

        Accepted shapes, each value being an entry or a list of entries:

        * ``{"files": [{<kind>: <entry>, ...}, ...]}`` (documented contract);
        * ``{"files": {<kind>: <entry>, ...}}``;
        * ``{"files": [<entry>, ...]}`` with already flat entries.

        Every returned entry carries its output kind in ``_kind`` (flat
        entries keep their own ``_kind``, if any). Unexpected values are
        ignored but logged, never silently dropped.
        """
        response = self._request("GET", f"/files/proc/{task_id}")
        payload = response.json()
        files = payload.get("files", []) if isinstance(payload, dict) else None

        flattened: List[Dict[str, Any]] = []
        if isinstance(files, dict):
            self._flatten_mapping(task_id, files, flattened)
        elif isinstance(files, list):
            for element in files:
                if isinstance(element, dict) and "file_id" in element:
                    flattened.append(dict(element))
                elif isinstance(element, dict):
                    self._flatten_mapping(task_id, element, flattened)
                else:
                    log.warning(
                        "Ignoring unexpected output element for task {}: {}",
                        _obscure(task_id),
                        type(element).__name__,
                    )
        else:
            log.warning(
                "Unexpected 'files' payload type for task {}: {}",
                _obscure(task_id),
                type(files).__name__,
            )
        return flattened

    @staticmethod
    def _flatten_mapping(
        task_id: str, mapping: Dict[str, Any], flattened: List[Dict[str, Any]]
    ) -> None:
        for kind, entry in mapping.items():
            entries = entry if isinstance(entry, list) else [entry]
            for item in entries:
                if isinstance(item, dict):
                    flattened.append({**item, "_kind": kind})
                else:
                    log.warning(
                        "Ignoring unexpected output entry of kind '{}' for task {}: {}",
                        kind,
                        _obscure(task_id),
                        type(item).__name__,
                    )
