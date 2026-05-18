"""Content-addressed object store protocol.

Layout (identical for filesystem and S3):
  {root}/raw/{source_id}/{yyyy}/{mm}/{sha256[:2]}/{sha256}.bin
  {root}/raw/{source_id}/{yyyy}/{mm}/{sha256[:2]}/{sha256}.json

The .bin file holds the raw fetched bytes; the .json sidecar holds fetch
metadata (url, timestamp, mime type, http status, headers). Content is
immutable once written; the sidecar is also written once — callers that
re-fetch the same content log a new CorpusEvent rather than overwriting.
"""

import json
from collections.abc import Iterable
from typing import Protocol, runtime_checkable


@runtime_checkable
class RawObjectStore(Protocol):
    def put(self, content_sha: str, body: bytes, sidecar: dict) -> str:
        """Idempotent write. Returns the URI for the stored body.

        If content_sha already exists the body write is skipped; the sidecar
        is NOT overwritten. Callers that need to record a re-fetch do so via
        a new CorpusEvent, not by updating the sidecar.
        """
        ...

    def get(self, content_sha: str) -> bytes: ...

    def get_sidecar(self, content_sha: str) -> dict: ...

    def exists(self, content_sha: str) -> bool: ...

    def iter_manifest(self) -> Iterable[str]:
        """Yield every content_sha present. Used when computing snapshot manifest hash."""
        ...

    def uri_for(self, content_sha: str) -> str:
        """Compute the URI for content_sha without touching the backend."""
        ...


def _object_path(source_id: str, content_sha: str) -> str:
    """Shared path fragment: raw/{source_id}/{sha[:2]}/{sha}"""
    return f"raw/{source_id}/{content_sha[:2]}/{content_sha}"


def sidecar_to_bytes(sidecar: dict) -> bytes:
    return json.dumps(sidecar, default=str).encode()


def sidecar_from_bytes(data: bytes) -> dict:
    return json.loads(data.decode())
