"""Tests for content-addressed object store.

Covers: put/get/exists round-trip on FS impl; sidecar stored separately from
body; second put with same sha is a no-op on body; manifest iteration; sha
computation stability.

Synthetic content only — no real fetched data.
"""

import hashlib

import pytest

from grants_ingest.storage.fs import FileSystemRawObjectStore


@pytest.fixture
def store(tmp_path):
    return FileSystemRawObjectStore(root=tmp_path)


BODY = b"Hello, synthetic content."
SHA = hashlib.sha256(BODY).hexdigest()
SIDECAR = {
    "source_id": "test_source",
    "fetch_url": "https://example.com/test",
    "fetched_at": "2026-05-18T00:00:00Z",
    "mime_type": "text/plain",
    "http_status": 200,
}


def test_put_get_round_trip(store):
    store.put(SHA, BODY, SIDECAR)
    assert store.get(SHA) == BODY


def test_sidecar_stored_separately(store):
    store.put(SHA, BODY, SIDECAR)
    sidecar = store.get_sidecar(SHA)
    assert sidecar["fetch_url"] == SIDECAR["fetch_url"]
    assert sidecar["source_id"] == SIDECAR["source_id"]


def test_exists_true_after_put(store):
    assert not store.exists(SHA)
    store.put(SHA, BODY, SIDECAR)
    assert store.exists(SHA)


def test_second_put_same_sha_is_noop(store, tmp_path):
    store.put(SHA, BODY, SIDECAR)
    first_stat = (tmp_path / "raw" / "test_source" / SHA[:2] / f"{SHA}.bin").stat()

    different_body = b"Different bytes, but we won't store them."
    store.put(SHA, different_body, SIDECAR)

    # Body must not have changed
    assert store.get(SHA) == BODY
    second_stat = (tmp_path / "raw" / "test_source" / SHA[:2] / f"{SHA}.bin").stat()
    assert first_stat.st_mtime == second_stat.st_mtime


def test_manifest_iteration(store):
    bodies = [f"body-{i}".encode() for i in range(3)]
    shas = []
    for i, body in enumerate(bodies):
        sha = FileSystemRawObjectStore.compute_sha(body)
        shas.append(sha)
        sidecar = {**SIDECAR, "source_id": f"src_{i}"}
        store.put(sha, body, sidecar)

    manifest = list(store.iter_manifest())
    for sha in shas:
        assert sha in manifest


def test_compute_sha_stability():
    sha1 = FileSystemRawObjectStore.compute_sha(BODY)
    sha2 = FileSystemRawObjectStore.compute_sha(BODY)
    assert sha1 == sha2 == SHA


def test_different_bodies_produce_different_shas():
    sha_a = FileSystemRawObjectStore.compute_sha(b"aaa")
    sha_b = FileSystemRawObjectStore.compute_sha(b"bbb")
    assert sha_a != sha_b


def test_uri_for_returns_file_uri(store):
    uri = store.uri_for(SHA, source_id="test_source")
    assert uri.startswith("file://")
    assert SHA in uri


def test_get_missing_raises(store):
    with pytest.raises(KeyError):
        store.get("deadbeef" * 8)
