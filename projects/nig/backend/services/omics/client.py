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
# Confirmed against the real Omics contract: a quota-exceeded condition is
# reported as HTTP 403 with body {"detail": "Storage limit reached"}.
QUOTA_STATUS_CODE = 403
QUOTA_DETAIL_MARKER = "storage limit reached"


def _obscure(identifier: str) -> str:
    """Truncate an id for logging, never print it in full."""
    if len(identifier) <= 8:
        return "***"
    return f"{identifier[:4]}...{identifier[-4:]}"


class OmicsClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: int = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
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
            detail = ""
            try:
                detail = str(response.json().get("detail", ""))
            except (ValueError, AttributeError):
                pass
            if QUOTA_DETAIL_MARKER in detail.lower():
                raise OmicsQuotaExceeded(
                    f"Omics storage quota exceeded (status {response.status_code}: "
                    f"{detail})"
                )
        raise OmicsRequestError(
            f"Omics request failed with status {response.status_code}",
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
        return response.json()

    def delete_file(self, file_id: str) -> bool:
        # Fallback cleanup path only: the caller must
        # only pass ids already registered in NIG's own graph.
        response = self._request("DELETE", f"/storage/objects/{file_id}")
        return response.ok

    def download_file(self, file_id: str, destination: Path) -> Path:
        response = self._request(
            "GET", f"/storage/objects/download/{file_id}", stream=True
        )
        tmp_path = destination.with_name(destination.name + ".part")
        with tmp_path.open("wb") as stream:
            for block in response.iter_content(chunk_size=1024 * 1024):
                if block:
                    stream.write(block)
        tmp_path.rename(destination)
        return destination

    # -- upload ---------------------------------------------------------------
    def upload_file(self, path: Path, tags: Optional[List[str]] = None) -> str:
        file_id = self._uploader.upload_file(path, tags=tags)
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

        The endpoint returns ``{"files": {<kind>: <entry-or-list>, ...}}``. 
        Unknown output kinds are ignored but logged, they
        are never silently dropped without a trace.
        """
        response = self._request("GET", f"/files/proc/{task_id}")
        payload = response.json()
        files_by_kind = payload.get("files", {})

        flattened: List[Dict[str, Any]] = []
        if isinstance(files_by_kind, dict):
            for kind, entry in files_by_kind.items():
                entries = entry if isinstance(entry, list) else [entry]
                for item in entries:
                    if isinstance(item, dict):
                        flattened.append({**item, "_kind": kind})
                    else:
                        log.warning(
                            "Ignoring unexpected /files/proc/{} entry of kind"
                            " '{}': {}",
                            task_id,
                            kind,
                            type(item),
                        )
        elif isinstance(files_by_kind, list):
            flattened = [f for f in files_by_kind if isinstance(f, dict)]
        else:
            log.warning(
                "Unexpected 'files' payload type in /files/proc/{}: {}",
                task_id,
                type(files_by_kind),
            )
        return flattened
