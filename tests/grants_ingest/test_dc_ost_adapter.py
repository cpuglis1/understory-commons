"""Tests for DCOSTAdapter — learn24.dc.gov two-pass fetch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from grants_ingest.adapters.dc_ost import DCOSTAdapter
from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.materialize import apply_events
from grants_ingest.models import OpportunityInstance
from grants_ingest.storage.fs import FileSystemRawObjectStore

FIXTURES = Path(__file__).parent / "fixtures" / "dc_ost"


def _make_store(tmp_path):
    return FileSystemRawObjectStore(root=str(tmp_path))


def _make_event_log():
    return EventLogWriter(source_id="gov_dc_ost", actor="system:gov_dc_ost_v0.1.0")


def _html_response(body: bytes, url: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", url),
    )


def _pdf_response(body: bytes, url: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "application/pdf", "content-length": str(len(body))},
        request=httpx.Request("GET", url),
    )


def _head_response(url: str, content_length: int) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-length": str(content_length)},
        request=httpx.Request("HEAD", url),
    )


@pytest.mark.django_db
def test_ost_index_emits_opportunity_seen(tmp_path):
    """Each index page fetch emits one OPPORTUNITY_SEEN."""
    store = _make_store(tmp_path)
    adapter = DCOSTAdapter(store=store, event_log=_make_event_log())

    ost_html = (FIXTURES / "ost_index.html").read_bytes()
    no_pdf_html = (FIXTURES / "ost_index_no_pdfs.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        body = ost_html if "ost-office-grants" in url else no_pdf_html
        return _html_response(body, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    seen = CorpusEvent.objects.filter(
        source_id="gov_dc_ost", event_type=CorpusEventType.OPPORTUNITY_SEEN
    )
    # 2 index pages → 2 base OPPORTUNITY_SEEN; ost_index has 2 PDFs → 2 more from pass 2
    assert seen.count() >= 2


@pytest.mark.django_db
def test_ost_native_pdfs_queued_and_fetched(tmp_path):
    """Native PDFs from ost_index.html are fetched as secondary RawRecords."""
    store = _make_store(tmp_path)
    adapter = DCOSTAdapter(store=store, event_log=_make_event_log())

    ost_html = (FIXTURES / "ost_index.html").read_bytes()
    pdf_body = (FIXTURES / "ost_supporting.pdf").read_bytes()

    def _fake_http(url, client, **kwargs):
        if url.endswith(".pdf"):
            return _pdf_response(pdf_body, url)
        return _html_response(ost_html, url)

    def _fake_head(url, **kwargs):
        return _head_response(url, len(pdf_body))

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        patch("httpx.Client") as mock_client_cls,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        # Pass 1 uses the patched http_get; Pass 2 uses a real client mock
        mock_client_cls.return_value.__enter__.return_value.head.side_effect = _fake_head
        mock_client_cls.return_value.__enter__.return_value.get.side_effect = (
            lambda url, **kw: _pdf_response(pdf_body, url)
        )
        # Re-patch http_get for pass 2 calls through fetch_one
        with patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http):
            adapter.run()

    # Both index pages return ost_html (each has 2 PDFs) → 4 total in queue
    assert len(adapter._pdf_queue) == 4


@pytest.mark.django_db
def test_ost_acrobat_links_logged_as_filtered(tmp_path):
    """Acrobat links in ost_index.html emit OPPORTUNITY_FILTERED, not fetched."""
    store = _make_store(tmp_path)
    adapter = DCOSTAdapter(store=store, event_log=_make_event_log())

    ost_html = (FIXTURES / "ost_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(ost_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        # Run with empty pdf_queue (no pass-2 client needed)
        adapter._pdf_queue.clear()
        # Manually call parse on the index to check acrobat logging
        from grants_ingest.adapters.types import FetchTask

        task = FetchTask(url=DCOSTAdapter._INDEX_URLS[0], expected_mime="text/html")
        client = type("FakeClient", (), {})()
        raw, _ = adapter.fetch_one(task, client)
        if raw:
            adapter.parse(raw)

    filtered = CorpusEvent.objects.filter(
        source_id="gov_dc_ost",
        event_type=CorpusEventType.OPPORTUNITY_FILTERED,
        payload__reason="external_link_unarchivable",
    )
    assert filtered.exists()
    assert filtered.first().payload["count"] == 2  # ost_index.html has 2 Acrobat links


@pytest.mark.django_db
def test_ost_no_pdfs_page_still_emits_seen(tmp_path):
    """Index page with no native PDFs still emits OPPORTUNITY_SEEN."""
    store = _make_store(tmp_path)
    adapter = DCOSTAdapter(store=store, event_log=_make_event_log())

    no_pdf_html = (FIXTURES / "ost_index_no_pdfs.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(no_pdf_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    seen = CorpusEvent.objects.filter(
        source_id="gov_dc_ost", event_type=CorpusEventType.OPPORTUNITY_SEEN
    )
    assert seen.count() == 2  # 2 index pages, no PDFs
    assert adapter._pdf_queue == []


@pytest.mark.django_db
def test_ost_idempotent_same_html_twice(tmp_path):
    """Running the adapter twice on identical HTML creates only one RawRecord per page."""
    store = _make_store(tmp_path)
    adapter1 = DCOSTAdapter(store=store, event_log=_make_event_log())
    adapter2 = DCOSTAdapter(store=store, event_log=_make_event_log())

    no_pdf_html = (FIXTURES / "ost_index_no_pdfs.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(no_pdf_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter1.run()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter2.run()

    from grants_ingest.raw_record import RawRecord

    # Same content → same sha → 1 unique RawRecord (content-addressed dedup)
    assert RawRecord.objects.filter(source_id="gov_dc_ost").count() == 1


@pytest.mark.django_db
def test_ost_robots_blocked(tmp_path):
    """Robots.txt blocking emits ROBOTS_BLOCKED and no OPPORTUNITY_SEEN."""
    store = _make_store(tmp_path)
    adapter = DCOSTAdapter(store=store, event_log=_make_event_log())

    with patch("grants_ingest.adapters.http._get_robots") as mock_robots:
        mock_robots.return_value.can_fetch.return_value = False
        result = adapter.run()

    assert result.robots_blocked == 2  # both index URLs blocked
    assert not CorpusEvent.objects.filter(
        source_id="gov_dc_ost", event_type=CorpusEventType.OPPORTUNITY_SEEN
    ).exists()


@pytest.mark.django_db
def test_ost_materializes_opportunity_rows(tmp_path):
    """After apply_events(), OpportunityInstance rows exist for OST index pages."""
    store = _make_store(tmp_path)
    adapter = DCOSTAdapter(store=store, event_log=_make_event_log())

    ost_html = (FIXTURES / "ost_index.html").read_bytes()
    no_pdf_html = (FIXTURES / "ost_index_no_pdfs.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        # Return distinct content per URL so each produces its own RawRecord
        body = ost_html if "ost-office-grants" in url else no_pdf_html
        return _html_response(body, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        patch.object(adapter, "_pdf_queue", []),  # skip pass 2 (no PDF fetching)
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    apply_events()
    assert OpportunityInstance.objects.filter(source_id="gov_dc_ost").count() == 2
