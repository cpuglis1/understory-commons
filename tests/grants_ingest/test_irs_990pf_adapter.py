"""Tests for IRS990PFAdapter — batch-zip ingest rewrite (2026-05-21).

Zip fixture contains three entries:
  matching_990pf.xml        — 990PF, EIN 990000099 (seed EIN) — should be stored + parsed
  nonmatching_990pf.xml     — 990PF, EIN 990000088 (not in seed) — must NOT be stored
  matching_990_wrongtype.xml — 990 (not 990PF), EIN 990000099 — must NOT be stored

Single-XML parse() behaviour is validated via the existing irs_990pf_synthetic.xml fixture
(no ReturnTypeCd; parse() does not filter — filtering is _process_zip's job).

EINs use the 99-XXXXXXX reserved prefix throughout.
"""

import hashlib
from pathlib import Path

import pytest
from django.utils import timezone

from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.adapters.irs_990pf import IRS990PFAdapter, _should_process
from grants_ingest.adapters.types import AdapterRunResult
from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.models import RawRecord
from grants_ingest.storage.fs import FileSystemRawObjectStore

FIXTURES = Path(__file__).parent / "fixtures"
ZIP_FIXTURE = FIXTURES / "irs_990pf_monthly_sample.zip"
XML_FIXTURE = FIXTURES / "irs_990pf_synthetic.xml"

SEED_EIN = "990000099"
NON_SEED_EIN = "990000088"


@pytest.fixture
def store(tmp_path):
    return FileSystemRawObjectStore(root=str(tmp_path))


@pytest.fixture
def event_log(db):
    return EventLogWriter(source_id="irs_990pf", actor="system:irs_990pf_v0.1.0")


@pytest.fixture
def adapter(store, event_log):
    return IRS990PFAdapter(
        store=store,
        event_log=event_log,
        seed_eins=[SEED_EIN],
        months_back=1,
    )


# ---------------------------------------------------------------------------
# _should_process unit tests (no DB required)
# ---------------------------------------------------------------------------


def test_should_process_matching_990pf():
    import zipfile

    with zipfile.ZipFile(ZIP_FIXTURE) as zf:
        xml_bytes = zf.read("matching_990pf.xml")
    ok, ein = _should_process(xml_bytes, {SEED_EIN})
    assert ok is True
    assert ein == SEED_EIN


def test_should_process_nonmatching_ein():
    import zipfile

    with zipfile.ZipFile(ZIP_FIXTURE) as zf:
        xml_bytes = zf.read("nonmatching_990pf.xml")
    ok, ein = _should_process(xml_bytes, {SEED_EIN})
    assert ok is False
    assert ein == NON_SEED_EIN


def test_should_process_wrong_form_type():
    import zipfile

    with zipfile.ZipFile(ZIP_FIXTURE) as zf:
        xml_bytes = zf.read("matching_990_wrongtype.xml")
    ok, ein = _should_process(xml_bytes, {SEED_EIN})
    assert ok is False


def test_should_process_malformed_xml():
    ok, ein = _should_process(b"<broken <<< xml", {SEED_EIN})
    assert ok is False
    assert ein == ""


# ---------------------------------------------------------------------------
# _process_zip integration tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_only_matching_990pf_produces_raw_record(adapter):
    result = AdapterRunResult(source_id="irs_990pf")
    adapter._process_zip(ZIP_FIXTURE.read_bytes(), "https://example.irs.gov/test.zip", result)

    assert RawRecord.objects.count() == 1
    assert result.stored_new == 1


@pytest.mark.django_db
def test_nonmatching_ein_never_reaches_store(adapter):
    result = AdapterRunResult(source_id="irs_990pf")
    adapter._process_zip(ZIP_FIXTURE.read_bytes(), "https://example.irs.gov/test.zip", result)

    stored = RawRecord.objects.all()
    for record in stored:
        assert record.fetch_metadata.get("ein") != NON_SEED_EIN


@pytest.mark.django_db
def test_wrong_form_type_never_reaches_store(adapter):
    """990 entry with matching EIN must not be stored (only 990PF passes)."""
    result = AdapterRunResult(source_id="irs_990pf")
    adapter._process_zip(ZIP_FIXTURE.read_bytes(), "https://example.irs.gov/test.zip", result)

    # 3 entries in zip, only 1 should be stored
    assert RawRecord.objects.count() == 1


@pytest.mark.django_db
def test_process_zip_emits_grant_events(adapter):
    result = AdapterRunResult(source_id="irs_990pf")
    adapter._process_zip(ZIP_FIXTURE.read_bytes(), "https://example.irs.gov/test.zip", result)

    grant_events = CorpusEvent.objects.filter(event_type=CorpusEventType.HISTORICAL_GRANT_RECORDED)
    assert grant_events.exists()
    payload = grant_events.first().payload
    assert payload["funder_ein"] == SEED_EIN


@pytest.mark.django_db
def test_process_zip_idempotent(adapter):
    """Running twice on the same zip produces the same number of RawRecords."""
    zip_bytes = ZIP_FIXTURE.read_bytes()
    result1 = AdapterRunResult(source_id="irs_990pf")
    result2 = AdapterRunResult(source_id="irs_990pf")
    adapter._process_zip(zip_bytes, "https://example.irs.gov/test.zip", result1)
    adapter._process_zip(zip_bytes, "https://example.irs.gov/test.zip", result2)

    assert RawRecord.objects.count() == 1
    assert result1.stored_new == 1
    assert result2.stored_new == 0  # second run: same sha, no new store


# ---------------------------------------------------------------------------
# parse() still works on a single XML (unchanged behaviour)
# ---------------------------------------------------------------------------


@pytest.fixture
def raw_record_from_xml_fixture(db, store):
    body = XML_FIXTURE.read_bytes()
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


@pytest.mark.django_db
def test_parse_produces_grant_events(store, event_log, raw_record_from_xml_fixture):
    adapter = IRS990PFAdapter(store=store, event_log=event_log, seed_eins=["990000050"])
    events = adapter.parse(raw_record_from_xml_fixture)
    grant_events = [e for e in events if e[0] == CorpusEventType.HISTORICAL_GRANT_RECORDED]
    assert len(grant_events) == 2


@pytest.mark.django_db
def test_parse_produces_funder_enriched(store, event_log, raw_record_from_xml_fixture):
    adapter = IRS990PFAdapter(store=store, event_log=event_log, seed_eins=["990000050"])
    events = adapter.parse(raw_record_from_xml_fixture)
    enriched = [e for e in events if e[0] == CorpusEventType.FUNDER_ENRICHED]
    assert len(enriched) == 1


@pytest.mark.django_db
def test_parse_grant_amounts(store, event_log, raw_record_from_xml_fixture):
    adapter = IRS990PFAdapter(store=store, event_log=event_log, seed_eins=["990000050"])
    events = adapter.parse(raw_record_from_xml_fixture)
    grants = [e[1] for e in events if e[0] == CorpusEventType.HISTORICAL_GRANT_RECORDED]
    amounts = {float(g["amount"]) for g in grants}
    assert 25000.0 in amounts
    assert 15000.0 in amounts


@pytest.mark.django_db
def test_parse_funder_ein(store, event_log, raw_record_from_xml_fixture):
    adapter = IRS990PFAdapter(store=store, event_log=event_log, seed_eins=["990000050"])
    events = adapter.parse(raw_record_from_xml_fixture)
    grants = [e[1] for e in events if e[0] == CorpusEventType.HISTORICAL_GRANT_RECORDED]
    assert all(g["funder_ein"] == "990000050" for g in grants)


@pytest.mark.django_db
def test_parse_malformed_xml_returns_parse_failed(store, event_log):
    body = b"<NotXML <<< broken"
    sha = hashlib.sha256(body).hexdigest()
    sidecar = {
        "source_id": "irs_990pf",
        "mime_type": "application/xml",
        "http_status": 200,
        "fetch_url": "https://x.com",
        "fetched_at": timezone.now().isoformat(),
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
    adapter = IRS990PFAdapter(store=store, event_log=event_log, seed_eins=[])
    events = adapter.parse(raw)
    assert events[0][0] == CorpusEventType.PARSE_FAILED


# ---------------------------------------------------------------------------
# iter_fetch_tasks URL generation
# ---------------------------------------------------------------------------


def test_iter_fetch_tasks_yields_correct_url_count():
    from datetime import date
    from unittest.mock import patch

    fixed_date = date(2026, 5, 21)
    with patch("grants_ingest.adapters.irs_990pf.date") as mock_date:
        mock_date.today.return_value = fixed_date
        adapter = IRS990PFAdapter(store=None, event_log=None, seed_eins=[], months_back=2)
        tasks = list(adapter.iter_fetch_tasks())

    # 2 months × 3 letters = 6 URLs
    assert len(tasks) == 6


def test_iter_fetch_tasks_url_format():
    from datetime import date
    from unittest.mock import patch

    fixed_date = date(2026, 5, 21)
    with patch("grants_ingest.adapters.irs_990pf.date") as mock_date:
        mock_date.today.return_value = fixed_date
        adapter = IRS990PFAdapter(store=None, event_log=None, seed_eins=[], months_back=1)
        tasks = list(adapter.iter_fetch_tasks())

    urls = [t.url for t in tasks]
    assert any("2026_TEOS_XML_05A.zip" in u for u in urls)
    assert any("2026_TEOS_XML_05B.zip" in u for u in urls)
    assert any("2026_TEOS_XML_05C.zip" in u for u in urls)


def test_iter_fetch_tasks_wraps_year_boundary():
    from datetime import date
    from unittest.mock import patch

    fixed_date = date(2026, 1, 15)
    with patch("grants_ingest.adapters.irs_990pf.date") as mock_date:
        mock_date.today.return_value = fixed_date
        adapter = IRS990PFAdapter(store=None, event_log=None, seed_eins=[], months_back=2)
        tasks = list(adapter.iter_fetch_tasks())

    urls = [t.url for t in tasks]
    # Month 0 = Jan 2026, Month -1 wraps to Dec 2025
    assert any("2025_TEOS_XML_12" in u for u in urls)
    assert any("2026_TEOS_XML_01" in u for u in urls)
