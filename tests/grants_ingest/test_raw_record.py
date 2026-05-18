"""Tests for RawRecord append-only enforcement."""

import pytest

from grants_ingest.models import RawRecord


@pytest.fixture
def raw_record(db):
    return RawRecord.objects.create(
        content_sha="a" * 64,
        fetch_url="https://example.com/test",
        fetched_at="2026-05-18T00:00:00Z",
        source_id="test_source",
        mime_type="application/json",
        content_ref="file:///var/lib/uc-corpus/raw/test_source/aa/aaa.bin",
        http_status=200,
    )


@pytest.mark.django_db
def test_raw_record_create(raw_record):
    assert RawRecord.objects.filter(content_sha="a" * 64).exists()


@pytest.mark.django_db
def test_raw_record_update_raises(raw_record):
    raw_record.http_status = 404
    with pytest.raises(ValueError, match="append-only"):
        raw_record.save()


@pytest.mark.django_db
def test_raw_record_content_sha_is_pk(raw_record):
    fetched = RawRecord.objects.get(pk="a" * 64)
    assert fetched.source_id == "test_source"
