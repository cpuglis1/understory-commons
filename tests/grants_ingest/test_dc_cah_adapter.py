"""Tests for DCAHAdapter — dcarts.dc.gov two-pass fetch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from grants_ingest.adapters.dc_cah import DCAHAdapter
from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.adapters.types import AdapterRunResult
from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.raw_record import RawRecord
from grants_ingest.storage.fs import FileSystemRawObjectStore

FIXTURES = Path(__file__).parent / "fixtures" / "dc_cah"


def _make_store(tmp_path):
    return FileSystemRawObjectStore(root=str(tmp_path))


def _make_event_log():
    return EventLogWriter(source_id="gov_dc_cah", actor="system:gov_dc_cah_v0.1.0")


def _html_response(body: bytes, url: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", url),
    )


@pytest.mark.django_db
def test_cah_index_discovers_grant_and_public_art_links(tmp_path):
    """Index page with /grants/ and /public-art/ links → 3 detail URLs queued.

    The self-link to /grants/grant-programs and external links are skipped.
    Absolute and relative hrefs to the same target are de-duped.
    """
    store = _make_store(tmp_path)
    adapter = DCAHAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "cah_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(index_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        patch.object(adapter, "_fetch_detail"),  # skip pass 2
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    assert len(adapter._detail_queue) == 3
    assert all("/grants/" in url or "/public-art/" in url for url in adapter._detail_queue)
    assert not any(url.endswith("/grant-programs") for url in adapter._detail_queue)


@pytest.mark.django_db
def test_cah_detail_with_pdf_emits_seen_and_queues_pdf(tmp_path):
    """Detail page with a native PDF link → OPPORTUNITY_SEEN + PDF queued."""
    store = _make_store(tmp_path)
    adapter = DCAHAdapter(store=store, event_log=_make_event_log())

    detail_html = (FIXTURES / "cah_detail_with_pdf.html").read_bytes()
    detail_url = "https://dcarts.dc.gov/grants/arts-and-humanities-education-project-grant-program"
    result = AdapterRunResult(source_id="gov_dc_cah")

    def _fake_http(url, client, **kwargs):
        return _html_response(detail_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        httpx.Client() as client,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter._fetch_detail(detail_url, client, result)

    ev = CorpusEvent.objects.filter(
        source_id="gov_dc_cah",
        event_type=CorpusEventType.OPPORTUNITY_SEEN,
    ).first()
    assert ev is not None
    assert ev.payload["funder_name_raw"] == "DC Commission on the Arts and Humanities"
    assert "Arts and Humanities Education" in ev.payload["title"]
    assert ev.payload["title"].endswith("Project Grant Program")  # ' | dcarts' stripped
    assert len(adapter._pdf_queue) == 1
    assert adapter._pdf_queue[0]["url"].endswith(".pdf")


@pytest.mark.django_db
def test_cah_detail_no_pdf_emits_seen_only(tmp_path):
    """Detail page with no PDF → OPPORTUNITY_SEEN emitted, no PDF queued.

    This is the FY27 pre-RFA-posting state per the plan §1.3.
    """
    store = _make_store(tmp_path)
    adapter = DCAHAdapter(store=store, event_log=_make_event_log())

    detail_html = (FIXTURES / "cah_detail_no_pdf.html").read_bytes()
    detail_url = "https://dcarts.dc.gov/grants/general-operating-support"
    result = AdapterRunResult(source_id="gov_dc_cah")

    def _fake_http(url, client, **kwargs):
        return _html_response(detail_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        httpx.Client() as client,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter._fetch_detail(detail_url, client, result)

    assert CorpusEvent.objects.filter(
        source_id="gov_dc_cah", event_type=CorpusEventType.OPPORTUNITY_SEEN
    ).exists()
    assert adapter._pdf_queue == []


@pytest.mark.django_db
def test_cah_idempotent(tmp_path):
    """Same detail page fetched twice → only one RawRecord stored (content-addressed)."""
    store = _make_store(tmp_path)
    adapter1 = DCAHAdapter(store=store, event_log=_make_event_log())
    adapter2 = DCAHAdapter(store=store, event_log=_make_event_log())

    detail_html = (FIXTURES / "cah_detail_no_pdf.html").read_bytes()
    detail_url = "https://dcarts.dc.gov/grants/general-operating-support"

    def _fake_http(url, client, **kwargs):
        return _html_response(detail_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        httpx.Client() as client,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter1._fetch_detail(detail_url, client, AdapterRunResult(source_id="gov_dc_cah"))
        adapter2._fetch_detail(detail_url, client, AdapterRunResult(source_id="gov_dc_cah"))

    assert RawRecord.objects.filter(source_id="gov_dc_cah").count() == 1


@pytest.mark.django_db
def test_cah_robots_blocked_on_index(tmp_path):
    """Robots.txt blocking on index → ROBOTS_BLOCKED event, no detail queued."""
    store = _make_store(tmp_path)
    adapter = DCAHAdapter(store=store, event_log=_make_event_log())

    with patch("grants_ingest.adapters.http._get_robots") as mock_robots:
        mock_robots.return_value.can_fetch.return_value = False
        result = adapter.run()

    assert result.robots_blocked == 1
    assert adapter._detail_queue == []
