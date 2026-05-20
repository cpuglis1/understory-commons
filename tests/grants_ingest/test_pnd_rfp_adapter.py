"""Tests for PNDRfpAdapter — RSS parsing and geo pre-filter.

Source-page fetch is tested in a separate file after commit #4.
Synthetic fixtures only.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.adapters.pnd_rfp import PNDRfpAdapter, _passes_geo_filter
from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.materialize import apply_events
from grants_ingest.models import OpportunityInstance
from grants_ingest.storage.fs import FileSystemRawObjectStore

FIXTURES = Path(__file__).parent / "fixtures"
RSS_FIXTURE = FIXTURES / "pnd_rss_sample.xml"
SOURCE_PAGE_FIXTURE = FIXTURES / "pnd_source_page.html"


def _make_store(tmp_path):
    return FileSystemRawObjectStore(root=str(tmp_path))


def _make_event_log():
    return EventLogWriter(source_id="pnd_rfp", actor="system:pnd_rfp_v0.1.0")


def _make_rss_response(body: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "application/rss+xml"},
        request=httpx.Request("GET", "https://philanthropynewsdigest.org/rfps/rss"),
    )


def _make_html_response(url: str, body: bytes = b"<html>stub</html>") -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", url),
    )


# --- Geo filter unit tests ---


def test_passes_geo_filter_national():
    assert _passes_geo_filter("national") is True


def test_passes_geo_filter_dmv():
    assert _passes_geo_filter("DMV area") is True


def test_passes_geo_filter_dc():
    assert _passes_geo_filter("District of Columbia") is True


def test_passes_geo_filter_md():
    assert _passes_geo_filter("Maryland nonprofits") is True


def test_passes_geo_filter_va():
    assert _passes_geo_filter("Virginia organizations") is True


def test_fails_geo_filter_texas():
    assert _passes_geo_filter("Texas") is False


def test_fails_geo_filter_empty():
    assert _passes_geo_filter("") is False


def test_fails_geo_filter_no_match():
    assert _passes_geo_filter("Pacific Northwest") is False


# --- Adapter integration tests ---


@pytest.mark.django_db
def test_pnd_rss_parsing_emits_opportunity_seen(tmp_path):
    """RSS items that pass geo filter emit OPPORTUNITY_SEEN events."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = PNDRfpAdapter(store=store, event_log=event_log)

    rss_body = RSS_FIXTURE.read_bytes()
    # Source page responses for the 3 passing items (guid-001, 002, 005)
    # and a re-publish of guid-001 (which becomes OPPORTUNITY_UPDATED)
    source_html = SOURCE_PAGE_FIXTURE.read_bytes()

    responses = [
        _make_rss_response(rss_body),
        _make_html_response("https://example-funder.org/rfp/national-youth-arts", source_html),
        _make_html_response("https://dmv-funder.org/rfp/afterschool-tutoring", source_html),
        _make_html_response("https://example-source-page.org/rfp/dc-youth-ed", source_html),
        # Re-publish of guid-001 (same GUID, updated deadline) source page
        _make_html_response("https://example-funder.org/rfp/national-youth-arts", source_html),
    ]

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.side_effect = responses
        adapter.run()

    # 3 unique passing GUIDs (001, 002, 005) → OPPORTUNITY_SEEN for each
    # guid-001 re-published with new deadline → OPPORTUNITY_UPDATED
    seen_events = CorpusEvent.objects.filter(
        source_id="pnd_rfp", event_type=CorpusEventType.OPPORTUNITY_SEEN
    )
    # guid-001 (first pass) + guid-002 + guid-005 → 3 initial SEEN events
    # The second run of guid-001 with changed date emits OPPORTUNITY_UPDATED, not SEEN
    assert seen_events.count() >= 3


@pytest.mark.django_db
def test_pnd_filtered_items_emit_filtered_event(tmp_path):
    """RSS items failing geo filter emit OPPORTUNITY_FILTERED."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = PNDRfpAdapter(store=store, event_log=event_log)

    rss_body = RSS_FIXTURE.read_bytes()
    source_html = SOURCE_PAGE_FIXTURE.read_bytes()

    responses = [
        _make_rss_response(rss_body),
        _make_html_response("https://example-funder.org/rfp/national-youth-arts", source_html),
        _make_html_response("https://dmv-funder.org/rfp/afterschool-tutoring", source_html),
        _make_html_response("https://example-source-page.org/rfp/dc-youth-ed", source_html),
        _make_html_response("https://example-funder.org/rfp/national-youth-arts", source_html),
    ]

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.side_effect = responses
        adapter.run()

    filtered_events = CorpusEvent.objects.filter(
        source_id="pnd_rfp", event_type=CorpusEventType.OPPORTUNITY_FILTERED
    )
    # guid-003 (Texas) and guid-004 (no geo) are filtered out
    assert filtered_events.count() == 2


@pytest.mark.django_db
def test_pnd_guid_dedup_within_run(tmp_path):
    """Same GUID appearing twice in one RSS fetch is only processed once."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = PNDRfpAdapter(store=store, event_log=event_log)

    rss_body = RSS_FIXTURE.read_bytes()
    source_html = SOURCE_PAGE_FIXTURE.read_bytes()

    responses = [
        _make_rss_response(rss_body),
        _make_html_response("https://example-funder.org/rfp/national-youth-arts", source_html),
        _make_html_response("https://dmv-funder.org/rfp/afterschool-tutoring", source_html),
        _make_html_response("https://example-source-page.org/rfp/dc-youth-ed", source_html),
        _make_html_response("https://example-funder.org/rfp/national-youth-arts", source_html),
    ]

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.side_effect = responses
        adapter.run()
    apply_events()

    # guid-001 appears twice in the fixture but produces only one OpportunityInstance
    opp_count = OpportunityInstance.objects.filter(external_id="pnd_rfp:pnd-guid-001").count()
    assert opp_count == 1


@pytest.mark.django_db
def test_pnd_updated_item_emits_opportunity_updated(tmp_path):
    """Re-published guid with changed deadline across two runs emits OPPORTUNITY_UPDATED.

    Within-run dedup skips a second occurrence of the same GUID in one RSS fetch.
    OPPORTUNITY_UPDATED fires on the SECOND run when the close date has changed.
    """
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = PNDRfpAdapter(store=store, event_log=event_log)
    source_html = SOURCE_PAGE_FIXTURE.read_bytes()

    # Run 1: guid-001 with "August 1, 2026" deadline
    rss_run1 = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>PND RFPs</title>
    <item>
      <title>National Youth Arts Initiative Grants</title>
      <link>https://example-funder.org/rfp/national-youth-arts</link>
      <guid isPermaLink="false">pnd-guid-upd-001</guid>
      <pubDate>Mon, 19 May 2026 12:00:00 +0000</pubDate>
      <description>Deadline: August 1, 2026. Geographic focus: National. Funder: Arts Foundation.</description>
    </item>
  </channel>
</rss>"""

    # Run 2: same guid-001 but different deadline
    rss_run2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>PND RFPs</title>
    <item>
      <title>National Youth Arts Initiative Grants</title>
      <link>https://example-funder.org/rfp/national-youth-arts</link>
      <guid isPermaLink="false">pnd-guid-upd-001</guid>
      <pubDate>Tue, 20 May 2026 12:00:00 +0000</pubDate>
      <description>Deadline: September 1, 2026. Geographic focus: National. Funder: Arts Foundation. UPDATED.</description>
    </item>
  </channel>
</rss>"""

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.side_effect = [
            _make_rss_response(rss_run1),
            _make_html_response("https://example-funder.org/rfp/national-youth-arts", source_html),
        ]
        adapter.run()

    # Run 2: guid-upd-001 now has a different deadline → OPPORTUNITY_UPDATED
    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.side_effect = [
            _make_rss_response(rss_run2),
            _make_html_response("https://example-funder.org/rfp/national-youth-arts", source_html),
        ]
        adapter.run()

    updated = CorpusEvent.objects.filter(
        source_id="pnd_rfp",
        event_type=CorpusEventType.OPPORTUNITY_UPDATED,
        payload__external_id="pnd_rfp:pnd-guid-upd-001",
    )
    assert updated.exists()


@pytest.mark.django_db
def test_pnd_run_second_time_idempotent(tmp_path):
    """Running twice with identical RSS produces no duplicate OpportunityInstance rows."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = PNDRfpAdapter(store=store, event_log=event_log)

    rss_body = RSS_FIXTURE.read_bytes()
    source_html = SOURCE_PAGE_FIXTURE.read_bytes()

    def make_responses():
        return [
            _make_rss_response(rss_body),
            _make_html_response("https://example-funder.org/rfp/national-youth-arts", source_html),
            _make_html_response("https://dmv-funder.org/rfp/afterschool-tutoring", source_html),
            _make_html_response("https://example-source-page.org/rfp/dc-youth-ed", source_html),
            _make_html_response("https://example-funder.org/rfp/national-youth-arts", source_html),
        ]

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.side_effect = make_responses()
        adapter.run()
    apply_events()

    count_after_first = OpportunityInstance.objects.count()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.side_effect = make_responses()
        adapter.run()
    apply_events()

    assert OpportunityInstance.objects.count() == count_after_first
