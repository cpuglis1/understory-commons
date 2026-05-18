"""Object store factory. Select backend via RAW_OBJECT_STORE_BACKEND setting."""

from django.conf import settings

from .base import RawObjectStore
from .fs import FileSystemRawObjectStore
from .s3 import S3RawObjectStore


def get_object_store() -> RawObjectStore:
    backend = getattr(settings, "RAW_OBJECT_STORE_BACKEND", "fs")
    if backend == "s3":
        return S3RawObjectStore(bucket=settings.RAW_OBJECT_STORE_S3_BUCKET)
    return FileSystemRawObjectStore(root=settings.RAW_OBJECT_STORE_FS_PATH)


__all__ = ["RawObjectStore", "FileSystemRawObjectStore", "S3RawObjectStore", "get_object_store"]
