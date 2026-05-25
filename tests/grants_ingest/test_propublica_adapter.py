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
    # object_id extracted from pdf_url → canonical IRS S3 XML URL
    assert (
        filings[0]["xml_url"] == "https://s3.amazonaws.com/irs-form-990/2022050112345678_public.xml"
    )
    assert (
        filings[1]["xml_url"] == "https://s3.amazonaws.com/irs-form-990/2021050187654321_public.xml"
    )


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


def _store_synthetic_org(
    store, tmp_path, org_overrides: dict, *, ein: str = "990000099"
) -> "RawRecord":
    """Helper: write a synthetic ProPublica org response into the store and DB."""
    import json

    base_org = {
        "ein": ein,
        "name": "Synthetic Test Foundation",
        "address": "1 Test Ave",
        "city": "Washington",
        "state": "DC",
        "zipcode": "20001",
        "ntee_code": "T20",
        "subsection_code": "3",
    }
    base_org.update(org_overrides)
    body = json.dumps(
        {"organization": base_org, "filings_with_data": [], "filings_without_data": []}
    ).encode()
    sha = hashlib.sha256(body).hexdigest()
    sidecar = {
        "source_id": "propublica_np",
        "mime_type": "application/json",
        "http_status": 200,
        "fetch_url": f"https://example.com/organizations/{ein}.json",
        "fetched_at": "2026-01-01T00:00:00",
    }
    store.put(sha, body, sidecar)
    from grants_ingest.models import RawRecord as RR

    return RR.objects.create(
        content_sha=sha,
        fetch_url=sidecar["fetch_url"],
        fetched_at=timezone.now(),
        source_id="propublica_np",
        mime_type="application/json",
        content_ref=store.uri_for(sha, source_id="propublica_np"),
        http_status=200,
    )


@pytest.mark.django_db
def test_parse_ntee_null_does_not_crash(store, event_log, tmp_path):
    """ntee_code: null in API response must not crash parse() (Bug 1 regression)."""
    raw = _store_synthetic_org(store, tmp_path, {"ntee_code": None}, ein="990000091")
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    events = adapter.parse(raw)
    assert len(events) == 1
    event_type, payload = events[0]
    assert event_type == CorpusEventType.FUNDER_UPSERTED
    assert "ntee" not in payload["notes"]


@pytest.mark.django_db
def test_parse_subsection_code_field_name(store, event_log, tmp_path):
    """ProPublica returns subsection_code not subseccd — Bug 2 regression."""
    raw = _store_synthetic_org(
        store,
        tmp_path,
        {"subsection_code": "3", "ntee_code": "T30"},
        ein="990000092",
    )
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw)[0]
    assert payload["notes"]["irs_subsection"] == "3"


@pytest.mark.django_db
def test_parse_subsection_code_92_infers_private_foundation(store, event_log, tmp_path):
    """subsection_code=92 via real API field name must yield funder_type=private_foundation."""
    raw = _store_synthetic_org(
        store,
        tmp_path,
        {"subsection_code": "92", "ntee_code": "T20"},
        ein="990000093",
    )
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw)[0]
    assert payload["funder_type"] == "private_foundation"


def _store_error_response(store, *, ein: str = "990000094") -> "RawRecord":
    """Helper: write a synthetic ProPublica 'Organization not found' error response."""
    import json

    body = json.dumps(
        {"data_source": "current_test", "api_version": "2.0", "error": "Organization not found"}
    ).encode()
    sha = hashlib.sha256(body).hexdigest()
    sidecar = {
        "source_id": "propublica_np",
        "mime_type": "application/json",
        "http_status": 200,
        "fetch_url": f"https://example.com/organizations/{ein}.json",
        "fetched_at": "2026-01-01T00:00:00",
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
def test_parse_error_response_emits_no_events(store, event_log, tmp_path):
    """ProPublica 'Organization not found' response must emit zero events (Bug 3 regression)."""
    from grants_ingest.models import Funder

    raw = _store_error_response(store)
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    events = adapter.parse(raw)
    assert events == []
    assert Funder.objects.count() == 0


@pytest.mark.django_db
def test_parse_foundation_code_4_infers_private_foundation(store, event_log, tmp_path):
    """foundation_code=4 (non-operating PF) must yield funder_type=private_foundation (Bug 8)."""
    raw = _store_synthetic_org(
        store,
        tmp_path,
        {"subsection_code": "3", "foundation_code": 4, "ntee_code": "T20"},
        ein="990000095",
    )
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw)[0]
    assert payload["funder_type"] == "private_foundation"


@pytest.mark.django_db
def test_parse_foundation_code_3_infers_private_foundation(store, event_log, tmp_path):
    """foundation_code=3 (operating PF) must also yield funder_type=private_foundation (Bug 8)."""
    raw = _store_synthetic_org(
        store,
        tmp_path,
        {"subsection_code": "3", "foundation_code": 3},
        ein="990000096",
    )
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw)[0]
    assert payload["funder_type"] == "private_foundation"


@pytest.mark.django_db
def test_parse_foundation_code_15_infers_public_charity(store, event_log, tmp_path):
    """foundation_code=15 ('not a private foundation') must NOT yield private_foundation."""
    raw = _store_synthetic_org(
        store,
        tmp_path,
        {"subsection_code": "3", "foundation_code": 15},
        ein="990000097",
    )
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw)[0]
    assert payload["funder_type"] == "public_charity"


@pytest.mark.django_db
def test_parse_filings_index_excludes_non_pf_formtype(store, event_log, tmp_path):
    """filings_with_data entries with formtype != 2 must not appear in filings_index."""
    import json

    body = json.dumps(
        {
            "organization": {
                "ein": "990000098",
                "name": "Public Charity Filing Test",
                "subsection_code": "3",
                "foundation_code": 15,
            },
            "filings_with_data": [
                {
                    "tax_prd_yr": 2022,
                    "formtype": 0,
                    "pdf_url": "https://projects.propublica.org/nonprofits/download-filing?path=IRS%2F990000098_202204_990_2022050199999999.pdf",
                    "totrevenue": 100000,
                }
            ],
            "filings_without_data": [],
        }
    ).encode()
    sha = __import__("hashlib").sha256(body).hexdigest()
    from django.utils import timezone

    from grants_ingest.models import RawRecord as RR

    sidecar = {
        "source_id": "propublica_np",
        "mime_type": "application/json",
        "http_status": 200,
        "fetch_url": "https://example.com/organizations/990000098.json",
        "fetched_at": "2026-01-01T00:00:00",
    }
    store.put(sha, body, sidecar)
    raw = RR.objects.create(
        content_sha=sha,
        fetch_url=sidecar["fetch_url"],
        fetched_at=timezone.now(),
        source_id="propublica_np",
        mime_type="application/json",
        content_ref=store.uri_for(sha, source_id="propublica_np"),
        http_status=200,
    )
    adapter = ProPublicaNPAdapter(store=store, event_log=event_log)
    _, payload = adapter.parse(raw)[0]
    assert "filings_index" not in payload["notes"]


def test_extract_object_id_new_format():
    """New-format ProPublica pdf_url yields a 16-digit object_id."""
    from grants_ingest.adapters.propublica_np import _extract_object_id

    url = "https://projects.propublica.org/nonprofits/download-filing?path=IRS%2F526036989_202404_990PF_2025010222973793.pdf"
    assert _extract_object_id(url) == "2025010222973793"


def test_extract_object_id_download990pdf_format():
    """download990pdf path variant also yields the correct object_id."""
    from grants_ingest.adapters.propublica_np import _extract_object_id

    url = "https://projects.propublica.org/nonprofits/download-filing?path=download990pdf_01_2024_prefixes_52-54%2F526036989_202304_990PF_2024011722244739.pdf"
    assert _extract_object_id(url) == "2024011722244739"


def test_extract_object_id_old_format_returns_none():
    """Old pre-e-file pdf_url format (no object_id, 6-digit period code) returns None."""
    from grants_ingest.adapters.propublica_np import _extract_object_id

    url = "https://projects.propublica.org/nonprofits/download-filing?path=2016_10_PF%2F52-6036989_990PF_201604.pdf"
    assert _extract_object_id(url) is None


def test_extract_object_id_empty_returns_none():
    """Empty string returns None without raising."""
    from grants_ingest.adapters.propublica_np import _extract_object_id

    assert _extract_object_id("") is None
