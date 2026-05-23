"""Tests for DCMOCAAdapter — communityaffairs.dc.gov three-pass fetch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from grants_ingest.adapters.dc_moca import DCMOCAAdapter
from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.adapters.types import AdapterRunResult
from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.raw_record import RawRecord
from grants_ingest.storage.fs import FileSystemRawObjectStore

FIXTURES = Path(__file__).parent / "fixtures" / "dc_moca"


def _make_store(tmp_path):
    return FileSystemRawObjectStore(root=str(tmp_path))


def _make_event_log():
    return EventLogWriter(source_id="gov_dc_moca", actor="system:gov_dc_moca_v0.1.0")


def _html_response(body: bytes, url: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", url),
    )


def _bin_response(body: bytes, url: str, mime: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": mime, "content-length": str(len(body))},
        request=httpx.Request("GET", url),
    )


def _head_response(url: str, size: int) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-length": str(size)},
        request=httpx.Request("HEAD", url),
    )


@pytest.mark.django_db
def test_moca_index_discovers_three_publication_urls(tmp_path):
    """Index page with 3 /publication/ links + 1 external → 3 publications queued."""
    store = _make_store(tmp_path)
    adapter = DCMOCAAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "moca_index.html").read_bytes()

    def _fake_http(url, client, **kwargs):
        return _html_response(index_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        patch.object(adapter, "_fetch_publication"),  # skip pass 2
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    assert len(adapter._publication_queue) == 3
    assert all("/publication/" in url for url in adapter._publication_queue)


@pytest.mark.django_db
def test_moca_pub_osse_emits_correct_funder(tmp_path):
    """Publication page with OSSE in title → funder_name_raw = OSSE canonical name."""
    store = _make_store(tmp_path)
    adapter = DCMOCAAdapter(store=store, event_log=_make_event_log())

    index_html = (FIXTURES / "moca_index.html").read_bytes()
    osse_html = (FIXTURES / "moca_pub_osse.html").read_bytes()
    pdf_body = (FIXTURES / "moca_attachment.pdf").read_bytes()
    docx_body = (FIXTURES / "moca_attachment.docx").read_bytes()

    pub_url = "https://communityaffairs.dc.gov/publication/fy27-osse-prek-enhancement-nofa"

    def _fake_http(url, client, **kwargs):
        if "community-grant-program" in url:
            return _html_response(index_html, url)
        if "osse" in url and url.endswith(".pdf"):
            return _bin_response(pdf_body, url, "application/pdf")
        if "osse" in url and url.endswith(".docx"):
            return _bin_response(
                docx_body,
                url,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        return _html_response(osse_html, url)

    result = AdapterRunResult(source_id="gov_dc_moca")
    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        httpx.Client() as client,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter._fetch_publication(pub_url, client, result)

    ev = CorpusEvent.objects.filter(
        source_id="gov_dc_moca",
        event_type=CorpusEventType.OPPORTUNITY_SEEN,
    ).first()
    assert ev is not None
    assert ev.payload["funder_name_raw"] == "DC Office of the State Superintendent of Education"
    assert "OSSE" in ev.payload["title"] or "Pre-K" in ev.payload["title"]


@pytest.mark.django_db
def test_moca_pub_no_agency_falls_back(tmp_path):
    """Publication page with no recognized agency → funder_name_raw = fallback string."""
    store = _make_store(tmp_path)
    adapter = DCMOCAAdapter(store=store, event_log=_make_event_log())

    no_agency_html = (FIXTURES / "moca_pub_no_agency.html").read_bytes()
    pub_url = "https://communityaffairs.dc.gov/publication/fy27-community-safety-nofa"
    result = AdapterRunResult(source_id="gov_dc_moca")

    def _fake_http(url, client, **kwargs):
        return _html_response(no_agency_html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        httpx.Client() as client,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter._fetch_publication(pub_url, client, result)

    ev = CorpusEvent.objects.filter(
        source_id="gov_dc_moca",
        event_type=CorpusEventType.OPPORTUNITY_SEEN,
    ).first()
    assert ev is not None
    assert ev.payload["funder_name_raw"] == "DC Government (agency unresolved)"


@pytest.mark.django_db
def test_moca_pub_no_attachments_emits_seen_only(tmp_path):
    """Publication page with no attachments → OPPORTUNITY_SEEN emitted, attachment queue empty."""
    store = _make_store(tmp_path)
    adapter = DCMOCAAdapter(store=store, event_log=_make_event_log())

    html = (FIXTURES / "moca_pub_no_attachments.html").read_bytes()
    pub_url = "https://communityaffairs.dc.gov/publication/fy27-does-youth-workforce-nofa"
    result = AdapterRunResult(source_id="gov_dc_moca")

    def _fake_http(url, client, **kwargs):
        return _html_response(html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        httpx.Client() as client,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter._fetch_publication(pub_url, client, result)

    assert CorpusEvent.objects.filter(
        source_id="gov_dc_moca", event_type=CorpusEventType.OPPORTUNITY_SEEN
    ).exists()
    assert adapter._attachment_queue == []


@pytest.mark.django_db
def test_moca_docx_stored_with_correct_mime(tmp_path):
    """DOCX attachment on OSSE publication page stored with DOCX MIME type."""
    store = _make_store(tmp_path)
    adapter = DCMOCAAdapter(store=store, event_log=_make_event_log())

    osse_html = (FIXTURES / "moca_pub_osse.html").read_bytes()
    pub_url = "https://communityaffairs.dc.gov/publication/fy27-osse-prek-enhancement-nofa"
    adapter._publication_queue.append(pub_url)

    def _fake_http(url, client, **kwargs):
        return _html_response(osse_html, url)

    result = AdapterRunResult(source_id="gov_dc_moca")
    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        httpx.Client() as client,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter._fetch_publication(pub_url, client, result)

    docx_items = [
        i for i in adapter._attachment_queue if i["mime"].endswith("wordprocessingml.document")
    ]
    assert len(docx_items) == 1


@pytest.mark.django_db
def test_moca_idempotent(tmp_path):
    """Same publication page fetched twice → only one RawRecord stored."""
    store = _make_store(tmp_path)
    adapter1 = DCMOCAAdapter(store=store, event_log=_make_event_log())
    adapter2 = DCMOCAAdapter(store=store, event_log=_make_event_log())

    html = (FIXTURES / "moca_pub_no_attachments.html").read_bytes()
    pub_url = "https://communityaffairs.dc.gov/publication/fy27-does-youth-workforce-nofa"

    def _fake_http(url, client, **kwargs):
        return _html_response(html, url)

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_http),
        httpx.Client() as client,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter1._fetch_publication(pub_url, client, AdapterRunResult(source_id="gov_dc_moca"))
        adapter2._fetch_publication(pub_url, client, AdapterRunResult(source_id="gov_dc_moca"))

    assert RawRecord.objects.filter(source_id="gov_dc_moca").count() == 1


@pytest.mark.django_db
def test_moca_robots_blocked_on_index(tmp_path):
    """Robots.txt blocking on index → ROBOTS_BLOCKED event, no OPPORTUNITY_SEEN."""
    store = _make_store(tmp_path)
    adapter = DCMOCAAdapter(store=store, event_log=_make_event_log())

    with patch("grants_ingest.adapters.http._get_robots") as mock_robots:
        mock_robots.return_value.can_fetch.return_value = False
        result = adapter.run()

    assert result.robots_blocked == 1
    assert adapter._publication_queue == []
