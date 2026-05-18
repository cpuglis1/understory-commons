"""Tests for ProPublicaNPAdapter.parse using a synthetic JSON fixture.

Verifies that all spec'd fields flow through to the funder_upserted event.
No live HTTP — fixture bytes are loaded from disk and injected via the FS store.
"""

import hashlib
from pathlib import Path

import pytest
from django.utils import timezone

from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.adapters.propublica_np import ProPublicaNPAdapter
from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.models import RawRecord
from grants_ingest.storage.fs import FileSystemRawObjectStore

FIXTURE = Path(__file__).parent / "fixtures" / "propublica_org_synthetic.json"


@pytest.fixture
def store(tmp_path):
    return FileSystemRawObjectStore(root=tmp_path)


@pytest.fixture
def event_log(db):
    return EventLogWriter(source_id="propublica_np", actor="system:propublica_np_v0.1.0")


@pytest.fixture
def raw_record(db, store):
    body = FIXTURE.read_bytes()
    sha = hashlib.sha256(body).hexdigest()
    sidecar = {
        "source_id": "propublica_np",
        "fetch_url": "https://example.com/organizations/990000040.json",
        "fetched_at": timezone.now().isoformat(),
        "mime_type": "application/json",
        "http_status": 200,
    }
    store.put(sha, body, sidecar)
    return RawRecord.objects.create(
        content_sha=sha,
        fetch_url=sidecar["fetch_url"],
        fetched_at=timezone.now(),
        source_id="propublica_np",
        mime_type="application/json",
        content_ref=store.uri_for(sha, source_id="propublica_np"),
        http_status=200,
    )


@pytest.mark.django_db
def test_parse_emits_funder_upserted(store, event_log, raw_record):
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    events = adapter.parse(raw_record)
    assert len(events) == 1
    event_type, payload = events[0]
    assert event_type == CorpusEventType.FUNDER_UPSERTED


@pytest.mark.django_db
def test_parse_ein_flows_through(store, event_log, raw_record):
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw_record)[0]
    assert payload["ein"] == "990000040"


@pytest.mark.django_db
def test_parse_name_flows_through(store, event_log, raw_record):
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw_record)[0]
    assert payload["canonical_name"] == "Synthetic Youth Foundation for Testing"


@pytest.mark.django_db
def test_parse_ntee_in_notes(store, event_log, raw_record):
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw_record)[0]
    assert payload["notes"]["ntee"] == "B90"


@pytest.mark.django_db
def test_parse_subsection_in_notes(store, event_log, raw_record):
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw_record)[0]
    assert payload["notes"]["irs_subsection"] == "92"


@pytest.mark.django_db
def test_parse_funder_type_private_foundation(store, event_log, raw_record):
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw_record)[0]
    assert payload["funder_type"] == "private_foundation"


@pytest.mark.django_db
def test_parse_annual_revenue_in_notes(store, event_log, raw_record):
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw_record)[0]
    assert "annual_revenue" in payload["notes"]
    assert "2022" in payload["notes"]["annual_revenue"]


@pytest.mark.django_db
def test_parse_filings_index_in_notes(store, event_log, raw_record):
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw_record)[0]
    filings = payload["notes"]["filings_index"]
    assert len(filings) == 2
    assert filings[0]["xml_url"] == "https://example.com/990pf_2022.xml"


@pytest.mark.django_db
def test_parse_address_in_notes(store, event_log, raw_record):
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw_record)[0]
    assert "address" in payload["notes"]
    assert "DC" in payload["notes"]["address"]


@pytest.mark.django_db
def test_parse_invalid_json_returns_parse_failed(store, event_log, tmp_path):
    """Malformed JSON body produces a parse_failed event, not an exception."""
    body = b"not json {"
    sha = hashlib.sha256(body).hexdigest()
    sidecar = {
        "source_id": "propublica_np",
        "mime_type": "application/json",
        "http_status": 200,
        "fetch_url": "https://x.com",
        "fetched_at": "2026-01-01",
    }
    store.put(sha, body, sidecar)
    raw = RawRecord.objects.create(
        content_sha=sha,
        fetch_url="https://x.com",
        fetched_at=timezone.now(),
        source_id="propublica_np",
        mime_type="application/json",
        content_ref=store.uri_for(sha, source_id="propublica_np"),
        http_status=200,
    )
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    events = adapter.parse(raw)
    assert events[0][0] == CorpusEventType.PARSE_FAILED
