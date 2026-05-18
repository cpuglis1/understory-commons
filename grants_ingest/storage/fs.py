"""Filesystem-backed content-addressed object store.

Root is configured via RAW_OBJECT_STORE_FS_PATH. Layout:
  {root}/raw/{source_id}/{sha[:2]}/{sha}.bin
  {root}/raw/{source_id}/{sha[:2]}/{sha}.json
"""

import hashlib
from collections.abc import Iterable
from pathlib import Path

from .base import _object_path, sidecar_from_bytes, sidecar_to_bytes


class FileSystemRawObjectStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _bin_path(self, source_id: str, content_sha: str) -> Path:
        return self._root / (_object_path(source_id, content_sha) + ".bin")

    def _json_path(self, source_id: str, content_sha: str) -> Path:
        return self._root / (_object_path(source_id, content_sha) + ".json")

    def _source_id_from_sha(self, content_sha: str) -> str | None:
        """Walk the raw/ tree to find which source_id owns this sha."""
        raw_dir = self._root / "raw"
        if not raw_dir.exists():
            return None
        for source_dir in raw_dir.iterdir():
            if source_dir.is_dir():
                bin_path = source_dir / content_sha[:2] / (content_sha + ".bin")
                if bin_path.exists():
                    return source_dir.name
        return None

    def put(self, content_sha: str, body: bytes, sidecar: dict) -> str:
        source_id = sidecar.get("source_id", "unknown")
        bin_path = self._bin_path(source_id, content_sha)
        json_path = self._json_path(source_id, content_sha)

        if not bin_path.exists():
            bin_path.parent.mkdir(parents=True, exist_ok=True)
            bin_path.write_bytes(body)
            json_path.write_bytes(sidecar_to_bytes(sidecar))

        return self.uri_for(content_sha, source_id=source_id)

    def get(self, content_sha: str) -> bytes:
        source_id = self._source_id_from_sha(content_sha)
        if source_id is None:
            raise KeyError(f"content_sha not found: {content_sha}")
        return self._bin_path(source_id, content_sha).read_bytes()

    def get_sidecar(self, content_sha: str) -> dict:
        source_id = self._source_id_from_sha(content_sha)
        if source_id is None:
            raise KeyError(f"content_sha not found: {content_sha}")
        return sidecar_from_bytes(self._json_path(source_id, content_sha).read_bytes())

    def exists(self, content_sha: str) -> bool:
        return self._source_id_from_sha(content_sha) is not None

    def iter_manifest(self) -> Iterable[str]:
        raw_dir = self._root / "raw"
        if not raw_dir.exists():
            return
        for bin_file in sorted(raw_dir.rglob("*.bin")):
            yield bin_file.stem

    def uri_for(self, content_sha: str, source_id: str = "unknown") -> str:
        return f"file://{self._bin_path(source_id, content_sha)}"

    @staticmethod
    def compute_sha(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()
