"""S3-backed content-addressed object store.

Thin pass-through over boto3. Not exercised in tests for slice 1;
verified on first production deploy. Activated by setting
RAW_OBJECT_STORE_BACKEND=s3 and RAW_OBJECT_STORE_S3_BUCKET.
"""

import hashlib
import json
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import boto3  # noqa: F401


class S3RawObjectStore:
    def __init__(self, bucket: str) -> None:
        import boto3

        self._bucket = bucket
        self._s3 = boto3.client("s3")

    def _bin_key(self, source_id: str, content_sha: str) -> str:
        return f"raw/{source_id}/{content_sha[:2]}/{content_sha}.bin"

    def _json_key(self, source_id: str, content_sha: str) -> str:
        return f"raw/{source_id}/{content_sha[:2]}/{content_sha}.json"

    def put(self, content_sha: str, body: bytes, sidecar: dict) -> str:
        source_id = sidecar.get("source_id", "unknown")
        bin_key = self._bin_key(source_id, content_sha)
        if not self.exists(content_sha):
            self._s3.put_object(Bucket=self._bucket, Key=bin_key, Body=body)
            self._s3.put_object(
                Bucket=self._bucket,
                Key=self._json_key(source_id, content_sha),
                Body=json.dumps(sidecar, default=str).encode(),
            )
        return self.uri_for(content_sha, source_id=source_id)

    def get(self, content_sha: str) -> bytes:
        source_id = self._find_source_id(content_sha)
        obj = self._s3.get_object(Bucket=self._bucket, Key=self._bin_key(source_id, content_sha))
        return obj["Body"].read()

    def get_sidecar(self, content_sha: str) -> dict:
        source_id = self._find_source_id(content_sha)
        obj = self._s3.get_object(Bucket=self._bucket, Key=self._json_key(source_id, content_sha))
        return json.loads(obj["Body"].read().decode())

    def exists(self, content_sha: str) -> bool:
        return self._find_source_id(content_sha) is not None

    def iter_manifest(self) -> Iterable[str]:
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix="raw/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".bin"):
                    yield key.rsplit("/", 1)[-1].removesuffix(".bin")

    def uri_for(self, content_sha: str, source_id: str = "unknown") -> str:
        return f"s3://{self._bucket}/{self._bin_key(source_id, content_sha)}"

    def _find_source_id(self, content_sha: str) -> str:
        paginator = self._s3.get_paginator("list_objects_v2")
        prefix = "raw/"
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(f"{content_sha[:2]}/{content_sha}.bin"):
                    return key.split("/")[1]
        raise KeyError(f"content_sha not found: {content_sha}")

    @staticmethod
    def compute_sha(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()
