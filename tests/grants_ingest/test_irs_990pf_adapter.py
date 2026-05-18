"""Tests for IRS990PFAdapter.parse using a synthetic 990-PF XML fixture.

EINs in the fixture use the 99-XXXXXXX / 00-XXXXXXX reserved prefixes.
No live HTTP — fixture bytes loaded from disk and injected via the FS store.
"""

import hashlib
from pathlib import Path

import pytest
from django.utils import timezone

from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.adapters.irs_990pf import IRS990PFAdapter
from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.models import RawRecord
from grants_ingest.storage.fs import FileSystemRawObjectStore

FIXTURE = Path(__file__).parent / "fixtures" / "irs_990pf_synthetic.xml"


@pytest.fixture
def store(tmp_path):
    return FileSystemRawObjectStore(root=tmp_path)


@pytest.fixture
def event_log(db):
    return EventLogWriter(source_id="irs_990pf", actor="system:irs_990pf_v0.1.0")


@pytest.fixture
def raw_record(db, store):
    body = FIXTURE.read_bytes()
    sha = hashlib.sha256(body).hexdigest()
    sidecar = {
        "source_id": "irs_990pf",
        "fetch_url": "https://example.com/990pf_2022.xml",
        "fetched_at": timezone.now().isoformat(),
        "mime_type": "application/xml",
        "http_status": 200,
    }
    store.put(sha, body, sidecar)
    return RawRecord.objects.create(
        content_sha=sha,
        fetch_url=sidecar["fetch_url"],
        fetched_at=timezone.now(),
        source_id="irs_990pf",
        mime_type="application/xml",
        content_ref=store.uri_for(sha, source_id="irs_990pf"),
        http_status=200,
    )


def _parse(store, event_log, raw_record):
    adapter = IRS990PFAdapter(store=store, event_log=event_log)
    return adapter.parse(raw_record)


@pytest.mark.django_db
def test_parse_produces_grant_events(store, event_log, raw_record):
    events = _parse(store, event_log, raw_record)
    grant_events = [e for e in events if e[0] == CorpusEventType.HISTORICAL_GRANT_RECORDED]
    assert len(grant_events) == 2


@pytest.mark.django_db
def test_parse_produces_funder_enriched(store, event_log, raw_record):
    events = _parse(store, event_log, raw_record)
    enriched = [e for e in events if e[0] == CorpusEventType.FUNDER_ENRICHED]
    assert len(enriched) == 1


@pytest.mark.django_db
def test_parse_grant_amount(store, event_log, raw_record):
    events = _parse(store, event_log, raw_record)
    grants = [e[1] for e in events if e[0] == CorpusEventType.HISTORICAL_GRANT_RECORDED]
    amounts = {float(g["amount"]) for g in grants}
    assert 25000.0 in amounts
    assert 15000.0 in amounts


@pytest.mark.django_db
def test_parse_funder_ein(store, event_log, raw_record):
    events = _parse(store, event_log, raw_record)
    grants = [e[1] for e in events if e[0] == CorpusEventType.HISTORICAL_GRANT_RECORDED]
    assert all(g["funder_ein"] == "990000050" for g in grants)


@pytest.mark.django_db
def test_parse_tax_year(store, event_log, raw_record):
    events = _parse(store, event_log, raw_record)
    grants = [e[1] for e in events if e[0] == CorpusEventType.HISTORICAL_GRANT_RECORDED]
    assert all(g["tax_year"] == 2022 for g in grants)


@pytest.mark.django_db
def test_parse_recipient_names(store, event_log, raw_record):
    events = _parse(store, event_log, raw_record)
    grants = [e[1] for e in events if e[0] == CorpusEventType.HISTORICAL_GRANT_RECORDED]
    names = {g["recipient_name_raw"] for g in grants}
    assert "Recipient Youth Org Alpha" in names
    assert "Recipient After-School Org Beta" in names


@pytest.mark.django_db
def test_parse_enrichment_application_info(store, event_log, raw_record):
    events = _parse(store, event_log, raw_record)
    enriched = [e[1] for e in events if e[0] == CorpusEventType.FUNDER_ENRICHED]
    notes = enriched[0]["notes"]
    assert "application_info_text" in notes
    assert "invitation" in notes["application_info_text"].lower()


@pytest.mark.django_db
def test_parse_malformed_xml_returns_parse_failed(store, event_log, tmp_path):
    body = b"<NotXML <<< broken"
    sha = hashlib.sha256(body).hexdigest()
    sidecar = {
        "source_id": "irs_990pf",
        "mime_type": "application/xml",
        "http_status": 200,
        "fetch_url": "https://x.com",
        "fetched_at": "2026-01-01",
    }
    store.put(sha, body, sidecar)
    raw = RawRecord.objects.create(
        content_sha=sha,
        fetch_url="https://x.com",
        fetched_at=timezone.now(),
        source_id="irs_990pf",
        mime_type="application/xml",
        content_ref=store.uri_for(sha, source_id="irs_990pf"),
        http_status=200,
    )
    adapter = IRS990PFAdapter(store=store, event_log=event_log)
    events = adapter.parse(raw)
    assert events[0][0] == CorpusEventType.PARSE_FAILED
