"""Tests for DCHumanitiesDCAdapter — humanitiesdc.org two-pass fetch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from grants_ingest.adapters.dc_humanitiesdc import DCHumanitiesDCAdapter
from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.materialize import apply_events
from grants_ingest.models import OpportunityInstance
from grants_ingest.raw_record import RawRecord
from grants_ingest.storage.fs import FileSystemRawObjectStore

FIXTURES = Path(__file__).parent / "fixtures" / "dc_humanitiesdc"


def _make_store(tmp_path):
    return FileSystemRawObjectStore(root=str(tmp_path))


def _make_event_log():
    return EventLogWriter(source_id="dc_humanitiesdc", actor="system:dc_humanitiesdc_v0.1.0")


def _html_response(body: bytes, url: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", url),
    )


@pytest.mark.django_db
def test_humanitiesdc_index_emits_seen_with_apply_url(tmp_path):
    """Index page → one OPPORTUNITY_SEEN with title, funder, and apply_url in notes."""
    store = _make_store(tmp_path)
    adapter = DCHumanitiesDCAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "humanitiesdc_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(index_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        patch.object(adapter, "_pdf_queue", []),  # skip PDF fetch
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    ev = CorpusEvent.objects.filter(
        source_id="dc_humanitiesdc",
        event_type=CorpusEventType.OPPORTUNITY_SEEN,
    ).first()
    assert ev is not None
    assert ev.payload["funder_name_raw"] == "HumanitiesDC"
    assert ev.payload["title"] == "Grant Opportunities"  # ' - HumanitiesDC' stripped
    assert ev.payload["notes"]["apply_url"].startswith("https://www.grantinterface.com")


@pytest.mark.django_db
def test_humanitiesdc_queues_all_native_pdfs(tmp_path):
    """Index with 6 wp-content/uploads PDFs → 6 entries in pdf queue."""
    store = _make_store(tmp_path)
    adapter = DCHumanitiesDCAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "humanitiesdc_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(index_html, url)

    # Stub fetch_attachment so the queue is populated by parse() but no PDF I/O runs
    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        patch("grants_ingest.adapters.dc_humanitiesdc.fetch_attachment"),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    assert len(adapter._pdf_queue) == 6
    assert all(item["url"].endswith(".pdf") for item in adapter._pdf_queue)
    assert all("wp-content/uploads" in item["url"] for item in adapter._pdf_queue)


@pytest.mark.django_db
def test_humanitiesdc_idempotent(tmp_path):
    """Running adapter twice on identical HTML stores only one RawRecord for the index."""
    store = _make_store(tmp_path)
    adapter1 = DCHumanitiesDCAdapter(store=store, event_log=_make_event_log())
    adapter2 = DCHumanitiesDCAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "humanitiesdc_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(index_html, url)

    for adapter in (adapter1, adapter2):
        with (
            patch("grants_ingest.adapters.http._get_robots") as mock_robots,
            patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
            patch.object(adapter, "_pdf_queue", []),
        ):
            mock_robots.return_value.can_fetch.return_value = True
            adapter.run()

    # Only the index page is fetched here (PDF queue skipped) → 1 unique RawRecord
    assert RawRecord.objects.filter(source_id="dc_humanitiesdc").count() == 1


@pytest.mark.django_db
def test_humanitiesdc_materializes_one_row_per_page(tmp_path):
    """After apply_events(), OpportunityInstance has one row per index page (Q2 V1 recommendation)."""
    store = _make_store(tmp_path)
    adapter = DCHumanitiesDCAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "humanitiesdc_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(index_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        patch.object(adapter, "_pdf_queue", []),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    apply_events()
    rows = OpportunityInstance.objects.filter(source_id="dc_humanitiesdc")
    assert rows.count() == 1
    row = rows.first()
    assert row.notes["apply_url"].startswith("https://www.grantinterface.com")
    assert row.funder_name_raw == "HumanitiesDC"


@pytest.mark.django_db
def test_humanitiesdc_robots_blocked(tmp_path):
    """robots.txt blocks → ROBOTS_BLOCKED, no OPPORTUNITY_SEEN."""
    store = _make_store(tmp_path)
    adapter = DCHumanitiesDCAdapter(store=store, event_log=_make_event_log())

    with patch("grants_ingest.adapters.http._get_robots") as mock_robots:
        mock_robots.return_value.can_fetch.return_value = False
        result = adapter.run()

    assert result.robots_blocked == 1
    assert not CorpusEvent.objects.filter(
        source_id="dc_humanitiesdc", event_type=CorpusEventType.OPPORTUNITY_SEEN
    ).exists()
