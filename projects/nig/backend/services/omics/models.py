"""Typed responses from the Omics REST API (issue #76).

Plain dataclasses, no I/O: they only shape the JSON payloads documented in
the integration plan (section 2) so the rest of the client/tasks code does
not manipulate raw dicts.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_expiry: Optional[int] = None


@dataclass
class StorageUsage:
    usage: int
    quota: int
    limit: float
    can_upload: bool = True


@dataclass
class UploadSession:
    upload_id: str
    recommended_chunk_size: int
    uploaded_parts: List[Dict[str, Any]] = field(default_factory=list)
    resuming: bool = False


@dataclass
class TaskInfo:
    task_id: str
    status: str
    start: Optional[str] = None
    end: Optional[str] = None
    elapsed_time: Optional[float] = None
    parameters: Optional[Dict[str, Any]] = None
