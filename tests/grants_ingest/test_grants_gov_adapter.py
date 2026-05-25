"""Tests for GrantsGovAdapter — daily XML extract + three pre-filter rules.

PDF fetch is tested separately in commit #6.
Synthetic fixtures only.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.adapters.grants_gov import (
    GrantsGovAdapter,
    _check_filter_rules,
    _looks_like_pdf_url,
)
from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.materialize import apply_events
from grants_ingest.models import OpportunityInstance
from grants_ingest.storage.fs import FileSystemRawObjectStore

FIXTURES = Path(__file__).parent / "fixtures"
EXTRACT_FIXTURE = FIXTURES / "grants_gov_extract.zip"


def _make_store(tmp_path):
    return FileSystemRawObjectStore(root=str(tmp_path))


def _make_event_log():
    return EventLogWriter(source_id="grants_gov", actor="system:grants_gov_v0.1.0")


def _make_zip_response(body: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "application/zip"},
        request=httpx.Request(
            "GET", "https://prod-grants-gov-chamel.s3.amazonaws.com/extracts/test.zip"
        ),
    )


# --- Filter rule unit tests ---


def test_filter_rule1_no_eligible_codes():
    result = _check_filter_rules([], ["84.287"], ["E"], "")
    assert result == "rule1_eligible_applicant"


def test_filter_rule1_wrong_eligible_code():
    result = _check_filter_rules(["01"], ["84.287"], ["E"], "")
    assert result == "rule1_eligible_applicant"


def test_filter_rule1_passes_code_25():
    result = _check_filter_rules(["25"], ["84.287"], ["E"], "")
    assert result is None


def test_filter_rule1_passes_code_12():
    result = _check_filter_rules(["12"], ["84.287"], ["E"], "")
    assert result is None


def test_filter_rule1_passes_multiple_codes_including_25():
    result = _check_filter_rules(["20", "25", "12"], ["84.010"], ["E"], "")
    assert result is None


def test_filter_rule2_bad_cfda_and_no_category():
    result = _check_filter_rules(["25"], ["15.000"], ["NR"], "")
    assert result == "rule2_cfda_or_category"


def test_filter_rule2_passes_cfda_84():
    result = _check_filter_rules(["25"], ["84.287"], [], "")
    assert result is None


def test_filter_rule2_passes_cfda_93_5():
    result = _check_filter_rules(["25"], ["93.500"], [], "")
    assert result is None


def test_filter_rule2_passes_cfda_16():
    result = _check_filter_rules(["25"], ["16.123"], [], "")
    assert result is None


def test_filter_rule2_passes_category_E():
    result = _check_filter_rules(["25"], ["15.000"], ["E"], "")
    assert result is None


def test_filter_rule2_passes_category_ED():
    result = _check_filter_rules(["25"], ["84.999"], ["ED"], "")
    assert result is None


def test_filter_rule2_passes_category_HL():
    result = _check_filter_rules(["25"], ["15.000"], ["HL"], "")
    assert result is None


def test_filter_rule3_floor_too_high():
    result = _check_filter_rules(["25"], ["84.287"], ["E"], "500000")
    assert result == "rule3_award_floor_too_high"


def test_filter_rule3_floor_at_limit_passes():
    # AwardFloor < 250000 passes; 249999 passes, 250000 fails
    result = _check_filter_rules(["25"], ["84.287"], ["E"], "249999")
    assert result is None


def test_filter_rule3_no_floor_passes():
    result = _check_filter_rules(["25"], ["84.287"], ["E"], "")
    assert result is None


def test_looks_like_pdf_url_true():
    assert _looks_like_pdf_url("https://example.gov/rfp/doc.pdf") is True


def test_looks_like_pdf_url_false_html():
    assert _looks_like_pdf_url("https://example.gov/rfp/page") is False


def test_looks_like_pdf_url_false_empty():
    assert _looks_like_pdf_url("") is False


# --- Adapter integration tests ---


@pytest.mark.django_db
def test_grants_gov_passing_opportunities_emit_seen(tmp_path):
    """Opportunities passing all 3 filter rules emit OPPORTUNITY_SEEN."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.return_value = _make_zip_response(zip_body)
        adapter.run()

    # 5 passing opportunities: #1, #5, #6, #7, #8
    # (#2 fails rule2, #3 fails rule1, #4 fails rule3)
    # #5 has a PDF URL → second OPPORTUNITY_SEEN emitted by _fetch_pdf → total 6
    seen = CorpusEvent.objects.filter(
        source_id="grants_gov", event_type=CorpusEventType.OPPORTUNITY_SEEN
    )
    assert seen.count() == 6


@pytest.mark.django_db
def test_grants_gov_failing_opportunities_emit_filtered(tmp_path):
    """Opportunities failing any filter rule emit OPPORTUNITY_FILTERED."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.return_value = _make_zip_response(zip_body)
        adapter.run()

    # #2 (rule2), #3 (rule1), #4 (rule3) → 3 filtered
    filtered = CorpusEvent.objects.filter(
        source_id="grants_gov", event_type=CorpusEventType.OPPORTUNITY_FILTERED
    )
    assert filtered.count() == 3


@pytest.mark.django_db
def test_grants_gov_rule1_failed_reason(tmp_path):
    """Rule 1 failure has correct reason in payload."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.return_value = _make_zip_response(zip_body)
        adapter.run()

    # OpportunityID 10003 (eligible=01) should have rule1 failure
    ev = CorpusEvent.objects.filter(
        source_id="grants_gov",
        event_type=CorpusEventType.OPPORTUNITY_FILTERED,
        payload__external_id="grants_gov:10003",
    ).first()
    assert ev is not None
    assert ev.payload["reason"] == "rule1_eligible_applicant"


@pytest.mark.django_db
def test_grants_gov_rule3_failed_reason(tmp_path):
    """Rule 3 failure (award floor too high) has correct reason in payload."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.return_value = _make_zip_response(zip_body)
        adapter.run()

    ev = CorpusEvent.objects.filter(
        source_id="grants_gov",
        event_type=CorpusEventType.OPPORTUNITY_FILTERED,
        payload__external_id="grants_gov:10004",
    ).first()
    assert ev is not None
    assert ev.payload["reason"] == "rule3_award_floor_too_high"


@pytest.mark.django_db
def test_grants_gov_multi_eligible_codes_passes(tmp_path):
    """Opportunity #7 with multiple EligibleApplicants codes including 25 passes."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.return_value = _make_zip_response(zip_body)
        adapter.run()

    ev = CorpusEvent.objects.filter(
        source_id="grants_gov",
        event_type=CorpusEventType.OPPORTUNITY_SEEN,
        payload__external_id="grants_gov:10007",
    ).first()
    assert ev is not None


@pytest.mark.django_db
def test_grants_gov_category_ed_passes_without_cfda(tmp_path):
    """Opportunity #8 with category ED passes even with non-standard CFDA."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.return_value = _make_zip_response(zip_body)
        adapter.run()

    ev = CorpusEvent.objects.filter(
        source_id="grants_gov",
        event_type=CorpusEventType.OPPORTUNITY_SEEN,
        payload__external_id="grants_gov:10008",
    ).first()
    assert ev is not None


@pytest.mark.django_db
def test_grants_gov_pdf_url_in_notes(tmp_path):
    """Opportunity #5 with PDF Description URL has it stored in notes."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.return_value = _make_zip_response(zip_body)
        adapter.run()

    ev = CorpusEvent.objects.filter(
        source_id="grants_gov",
        event_type=CorpusEventType.OPPORTUNITY_SEEN,
        payload__external_id="grants_gov:10005",
    ).first()
    assert ev is not None
    assert "description_pdf_url" in ev.payload.get("notes", {})


@pytest.mark.django_db
def test_grants_gov_materializes_opportunity_rows(tmp_path):
    """After apply_events(), OpportunityInstance rows exist for all passing items."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.return_value = _make_zip_response(zip_body)
        adapter.run()

    apply_events()
    assert OpportunityInstance.objects.filter(source_id="grants_gov").count() == 5


@pytest.mark.django_db
def test_grants_gov_pdf_fetched_as_second_raw_record(tmp_path):
    """Opportunity #5 with PDF URL: PDF is fetched as a separate RawRecord and M2M-linked."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()
    pdf_body = (FIXTURES / "grants_gov_fake_rfp.pdf").read_bytes()

    def _fake_head(url, **kwargs):
        resp = httpx.Response(
            200,
            headers={"content-length": str(len(pdf_body))},
            request=httpx.Request("HEAD", url),
        )
        return resp

    def _fake_get(*args, **kwargs):
        # Return a different response based on URL
        url = args[0] if args else kwargs.get("url", "")
        if url == adapter.extract_url:
            return httpx.Response(
                200,
                content=zip_body,
                headers={"content-type": "application/zip"},
                request=httpx.Request("GET", url),
            )
        # PDF request
        return httpx.Response(
            200,
            content=pdf_body,
            headers={"content-type": "application/pdf"},
            request=httpx.Request("GET", url),
        )

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get", side_effect=_fake_get),
    ):
        mock_robots.return_value.can_fetch.return_value = True
        adapter.run()

    apply_events()

    opp = OpportunityInstance.objects.filter(external_id="grants_gov:10005").first()
    assert opp is not None
    # Should have at least 2 source records: the zip extract + the PDF
    assert opp.source_records.count() >= 2


@pytest.mark.django_db
def test_grants_gov_non_pdf_description_not_fetched(tmp_path):
    """Opportunity #6 with HTML description URL does not trigger PDF fetch."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()

    with (
        patch("grants_ingest.adapters.http._get_robots") as mock_robots,
        patch("grants_ingest.adapters.base.http_get") as mock_http,
    ):
        mock_robots.return_value.can_fetch.return_value = True
        mock_http.return_value = _make_zip_response(zip_body)
        adapter.run()

    # Only the zip extract is in the PDF queue, not HTML description
    opp_6_event = CorpusEvent.objects.filter(
        source_id="grants_gov",
        event_type=CorpusEventType.OPPORTUNITY_SEEN,
        payload__external_id="grants_gov:10006",
    ).first()
    assert opp_6_event is not None
    assert "description_pdf_url" not in opp_6_event.payload.get("notes", {})


@pytest.mark.django_db
def test_grants_gov_idempotent_second_run(tmp_path):
    """Running twice produces the same number of OpportunityInstance rows."""
    store = _make_store(tmp_path)
    event_log = _make_event_log()
    adapter = GrantsGovAdapter(store=store, event_log=event_log)

    zip_body = EXTRACT_FIXTURE.read_bytes()

    def run_once():
        with (
            patch("grants_ingest.adapters.http._get_robots") as mock_robots,
            patch("grants_ingest.adapters.base.http_get") as mock_http,
        ):
            mock_robots.return_value.can_fetch.return_value = True
            mock_http.return_value = _make_zip_response(zip_body)
            adapter.run()
        apply_events()

    run_once()
    count_after_first = OpportunityInstance.objects.filter(source_id="grants_gov").count()
    run_once()
    assert OpportunityInstance.objects.filter(source_id="grants_gov").count() == count_after_first
