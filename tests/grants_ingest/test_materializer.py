"""Tests for materialize.apply_events: idempotency and replay correctness.

Synthetic fixtures only. EINs use the 99-XXXXXXX reserved prefix.
"""

import pytest
from django.utils import timezone

from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.materialize import apply_events
from grants_ingest.models import Funder, HistoricalGrant, OpportunityInstance, RawRecord


def _event(event_type, payload, content_sha=""):
    return CorpusEvent.objects.create(
        timestamp=timezone.now(),
        event_type=event_type,
        source_id="test_source",
        content_sha=content_sha,
        payload=payload,
        actor="system:test",
    )


def _raw_record(sha="c" * 64):
    return RawRecord.objects.create(
        content_sha=sha,
        fetch_url="https://example.com/filing.xml",
        fetched_at=timezone.now(),
        source_id="irs_990pf",
        mime_type="application/xml",
        content_ref=f"file:///tmp/{sha}.bin",
        http_status=200,
    )


@pytest.mark.django_db
def test_funder_upserted_creates_funder():
    _event(
        CorpusEventType.FUNDER_UPSERTED,
        {
            "ein": "990000020",
            "canonical_name": "Synthetic Youth Foundation",
            "funder_type": "private_foundation",
        },
    )
    apply_events()
    assert Funder.objects.filter(ein="990000020").exists()


@pytest.mark.django_db
def test_apply_events_idempotent():
    """Replaying the same events twice produces the same state."""
    _event(
        CorpusEventType.FUNDER_UPSERTED,
        {
            "ein": "990000021",
            "canonical_name": "Idempotent Foundation",
            "funder_type": "private_foundation",
        },
    )
    apply_events()
    apply_events(since_event_id=0)
    assert Funder.objects.filter(ein="990000021").count() == 1


@pytest.mark.django_db
def test_funder_enriched_updates_notes():
    _event(
        CorpusEventType.FUNDER_UPSERTED,
        {
            "ein": "990000022",
            "canonical_name": "Enrichable Foundation",
            "funder_type": "private_foundation",
        },
    )
    _event(
        CorpusEventType.FUNDER_ENRICHED,
        {
            "ein": "990000022",
            "notes": {"application_info_text": "Apply online."},
            "accepts_unsolicited": True,
        },
    )
    apply_events()
    funder = Funder.objects.get(ein="990000022")
    assert funder.notes.get("application_info_text") == "Apply online."
    assert funder.accepts_unsolicited is True


@pytest.mark.django_db
def test_historical_grant_recorded():
    raw = _raw_record()
    _event(
        CorpusEventType.FUNDER_UPSERTED,
        {
            "ein": "990000023",
            "canonical_name": "Grant Foundation",
            "funder_type": "private_foundation",
        },
    )
    _event(
        CorpusEventType.HISTORICAL_GRANT_RECORDED,
        {
            "funder_ein": "990000023",
            "tax_year": 2022,
            "recipient_name_raw": "Synthetic Youth Org",
            "amount": "15000.00",
            "purpose": "Youth programming",
        },
        content_sha=raw.content_sha,
    )
    apply_events()
    assert HistoricalGrant.objects.filter(funder__ein="990000023").count() == 1


@pytest.mark.django_db
def test_replay_from_zero_rebuilds_state():
    """Drop all Funder rows, replay from 0 — state is restored."""
    _event(
        CorpusEventType.FUNDER_UPSERTED,
        {
            "ein": "990000024",
            "canonical_name": "Replayable Foundation",
            "funder_type": "private_foundation",
        },
    )
    apply_events()
    assert Funder.objects.filter(ein="990000024").exists()

    Funder.objects.filter(ein="990000024").delete()
    assert not Funder.objects.filter(ein="990000024").exists()

    apply_events(since_event_id=0)
    assert Funder.objects.filter(ein="990000024").exists()


# --- OpportunityInstance materializer tests ---


def _opp_seen_payload(
    source_id="pnd_rfp",
    external_id="pnd_rfp:guid-001",
    title="Youth Arts Grant",
    sha=None,
):
    return {
        "source_id": source_id,
        "external_id": external_id,
        "title": title,
        "funder_name_raw": "Synthetic Arts Foundation",
        "notes": {"pnd_guid": "guid-001"},
        "content_sha": sha or "",
    }


@pytest.mark.django_db
def test_opportunity_seen_creates_row():
    _event(CorpusEventType.OPPORTUNITY_SEEN, _opp_seen_payload())
    apply_events()
    assert OpportunityInstance.objects.filter(external_id="pnd_rfp:guid-001").exists()


@pytest.mark.django_db
def test_opportunity_seen_idempotent():
    """Applying OPPORTUNITY_SEEN twice produces exactly one row."""
    payload = _opp_seen_payload()
    _event(CorpusEventType.OPPORTUNITY_SEEN, payload)
    _event(CorpusEventType.OPPORTUNITY_SEEN, payload)
    apply_events()
    assert OpportunityInstance.objects.filter(external_id="pnd_rfp:guid-001").count() == 1


@pytest.mark.django_db
def test_opportunity_seen_links_raw_record():
    _raw_record(sha="a" * 64)
    payload = _opp_seen_payload(sha="a" * 64)
    _event(CorpusEventType.OPPORTUNITY_SEEN, payload)
    apply_events()
    opp = OpportunityInstance.objects.get(external_id="pnd_rfp:guid-001")
    assert opp.source_records.filter(content_sha="a" * 64).exists()


@pytest.mark.django_db
def test_opportunity_updated_changes_close_date():
    _event(CorpusEventType.OPPORTUNITY_SEEN, _opp_seen_payload())
    apply_events()

    updated_payload = {
        **_opp_seen_payload(),
        "application_close_at": "2026-09-01T00:00:00Z",
    }
    _event(CorpusEventType.OPPORTUNITY_UPDATED, updated_payload)
    apply_events()

    opp = OpportunityInstance.objects.get(external_id="pnd_rfp:guid-001")
    assert opp.application_close_at is not None
    assert str(opp.application_close_at.year) == "2026"


@pytest.mark.django_db
def test_opportunity_replay_from_zero():
    """Drop OpportunityInstance rows, replay from 0 — state is restored."""
    _event(
        CorpusEventType.OPPORTUNITY_SEEN,
        _opp_seen_payload(
            source_id="grants_gov",
            external_id="grants_gov:99001",
            title="Federal Youth Education Grant",
        ),
    )
    apply_events()
    assert OpportunityInstance.objects.filter(external_id="grants_gov:99001").exists()

    OpportunityInstance.objects.filter(external_id="grants_gov:99001").delete()
    apply_events(since_event_id=0)
    assert OpportunityInstance.objects.filter(external_id="grants_gov:99001").exists()
