"""Tests for DCEventsDCAdapter — eventsdc.com one-pass + PDF fetch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from grants_ingest.adapters.dc_eventsdc import DCEventsDCAdapter
from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.materialize import apply_events
from grants_ingest.models import OpportunityInstance
from grants_ingest.raw_record import RawRecord
from grants_ingest.storage.fs import FileSystemRawObjectStore

FIXTURES = Path(__file__).parent / "fixtures" / "dc_eventsdc"


def _make_store(tmp_path):
    return FileSystemRawObjectStore(root=str(tmp_path))


def _make_event_log():
    return EventLogWriter(source_id="dc_eventsdc", actor="system:dc_eventsdc_v0.1.0")


def _html_response(body: bytes, url: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", url),
    )


@pytest.mark.django_db
def test_eventsdc_index_emits_seen_with_title_and_funder(tmp_path):
    """Index page → one OPPORTUNITY_SEEN with stripped title and Events DC funder."""
    store = _make_store(tmp_path)
    adapter = DCEventsDCAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "eventsdc_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(index_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        patch("grants_ingest.adapters.dc_eventsdc.fetch_attachment"),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    ev = CorpusEvent.objects.filter(
        source_id="dc_eventsdc",
        event_type=CorpusEventType.OPPORTUNITY_SEEN,
    ).first()
    assert ev is not None
    assert ev.payload["funder_name_raw"] == "Events DC"
    assert ev.payload["title"] == "Community Grants"  # ' | Events DC' stripped


@pytest.mark.django_db
def test_eventsdc_queues_native_pdfs(tmp_path):
    """Index with 2 native PDFs (absolute + relative) → both queued."""
    store = _make_store(tmp_path)
    adapter = DCEventsDCAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "eventsdc_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(index_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        patch("grants_ingest.adapters.dc_eventsdc.fetch_attachment"),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    assert len(adapter._pdf_queue) == 2
    # Both end up absolute after normalization
    assert all(item["url"].startswith("https://eventsdc.com") for item in adapter._pdf_queue)
    assert all(item["url"].endswith(".pdf") for item in adapter._pdf_queue)


@pytest.mark.django_db
def test_eventsdc_idempotent(tmp_path):
    """Running adapter twice on identical HTML stores only one RawRecord for the index."""
    store = _make_store(tmp_path)
    adapter1 = DCEventsDCAdapter(store=store, event_log=_make_event_log())
    adapter2 = DCEventsDCAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "eventsdc_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(index_html, url)

    for adapter in (adapter1, adapter2):
        with (
            patch("grants_ingest.adapters.http._get_robots") as mock_robots,
            patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
            patch("grants_ingest.adapters.dc_eventsdc.fetch_attachment"),
        ):
            mock_robots.return_value.can_fetch.return_value = True
            adapter.run()

    assert RawRecord.objects.filter(source_id="dc_eventsdc").count() == 1


@pytest.mark.django_db
def test_eventsdc_materializes_one_row(tmp_path):
    """After apply_events(), one OpportunityInstance row per index page."""
    store = _make_store(tmp_path)
    adapter = DCEventsDCAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "eventsdc_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(index_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        patch("grants_ingest.adapters.dc_eventsdc.fetch_attachment"),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    apply_events()
    rows = OpportunityInstance.objects.filter(source_id="dc_eventsdc")
    assert rows.count() == 1
    assert rows.first().title == "Community Grants"
