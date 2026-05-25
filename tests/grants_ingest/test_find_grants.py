"""Tests for the find_grants management command filter logic.

Tests exercise _build_queryset() directly using fixture OpportunityInstance rows.
Output formatting is verified with a simple smoke-test call via call_command().
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from grants_ingest.management.commands.find_grants import _build_queryset
from grants_ingest.opportunity import OpportunityInstance

FUTURE = datetime(2027, 1, 1, tzinfo=UTC)
PAST = datetime(2020, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 5, 20, tzinfo=UTC)


def _make_opp(**kwargs) -> OpportunityInstance:
    defaults = {
        "title": "Test Grant",
        "source_id": "grants_gov",
        "external_id": f"grants_gov:test_{id(kwargs)}",
        "funder_name_raw": "Test Agency",
        "first_seen_at": NOW,
        "last_seen_at": NOW,
        "subject_areas": ["E"],
    }
    defaults.update(kwargs)
    return OpportunityInstance.objects.create(**defaults)


@pytest.mark.django_db
def test_open_only_excludes_past_close_date():
    _make_opp(external_id="g:past", application_close_at=PAST)
    _make_opp(external_id="g:future", application_close_at=FUTURE)
    _make_opp(external_id="g:no_close")

    qs = _build_queryset({"open_only": True})
    eids = list(qs.values_list("external_id", flat=True))
    assert "g:past" not in eids
    assert "g:future" in eids
    assert "g:no_close" in eids


@pytest.mark.django_db
def test_award_min_gte_filter():
    _make_opp(external_id="g:small", award_min=Decimal("5000"))
    _make_opp(external_id="g:big", award_min=Decimal("50000"))
    _make_opp(external_id="g:no_min")

    qs = _build_queryset({"award_min_gte": 10000})
    eids = list(qs.values_list("external_id", flat=True))
    assert "g:small" not in eids
    assert "g:big" in eids
    assert "g:no_min" not in eids


@pytest.mark.django_db
def test_award_max_lte_filter():
    _make_opp(external_id="g:under", award_max=Decimal("100000"))
    _make_opp(external_id="g:over", award_max=Decimal("1000000"))

    qs = _build_queryset({"award_max_lte": 500000})
    eids = list(qs.values_list("external_id", flat=True))
    assert "g:under" in eids
    assert "g:over" not in eids


@pytest.mark.django_db
def test_source_filter():
    _make_opp(external_id="g:gov", source_id="grants_gov")
    _make_opp(external_id="pnd_rfp:t1", source_id="pnd_rfp")

    qs = _build_queryset({"sources": ["grants_gov"]})
    eids = list(qs.values_list("external_id", flat=True))
    assert "g:gov" in eids
    assert "pnd_rfp:t1" not in eids


@pytest.mark.django_db
def test_subject_areas_or_logic():
    _make_opp(external_id="g:edu", subject_areas=["E", "ED"])
    _make_opp(external_id="g:hl", subject_areas=["HL"])
    _make_opp(external_id="g:other", subject_areas=["AG"])

    qs = _build_queryset({"subject_areas": ["E", "HL"]})
    eids = list(qs.values_list("external_id", flat=True))
    assert "g:edu" in eids
    assert "g:hl" in eids
    assert "g:other" not in eids


@pytest.mark.django_db
def test_funder_name_contains_case_insensitive():
    _make_opp(external_id="g:ed1", funder_name_raw="Department of Education")
    _make_opp(external_id="g:hhs", funder_name_raw="Dept of Health")

    qs = _build_queryset({"funder_name_contains": "education"})
    eids = list(qs.values_list("external_id", flat=True))
    assert "g:ed1" in eids
    assert "g:hhs" not in eids


@pytest.mark.django_db
def test_combined_filters():
    _make_opp(
        external_id="g:pass",
        source_id="grants_gov",
        award_min=Decimal("15000"),
        subject_areas=["E"],
        application_close_at=FUTURE,
    )
    _make_opp(
        external_id="g:fail_source",
        source_id="pnd_rfp",
        award_min=Decimal("15000"),
        subject_areas=["E"],
        application_close_at=FUTURE,
    )
    _make_opp(
        external_id="g:fail_amount",
        source_id="grants_gov",
        award_min=Decimal("1000"),
        subject_areas=["E"],
        application_close_at=FUTURE,
    )

    qs = _build_queryset(
        {
            "open_only": True,
            "award_min_gte": 10000,
            "sources": ["grants_gov"],
            "subject_areas": ["E"],
        }
    )
    eids = list(qs.values_list("external_id", flat=True))
    assert "g:pass" in eids
    assert "g:fail_source" not in eids
    assert "g:fail_amount" not in eids


@pytest.mark.django_db
def test_no_filters_returns_all(tmp_path):
    _make_opp(external_id="g:a")
    _make_opp(external_id="g:b", source_id="pnd_rfp")
    assert _build_queryset({}).count() >= 2


@pytest.mark.django_db
def test_call_command_table_output(tmp_path):
    _make_opp(
        external_id="g:cmd_test",
        title="Command Test Grant",
        subject_areas=["E"],
        application_close_at=FUTURE,
    )
    profile = tmp_path / "profile.yaml"
    profile.write_text("filters:\n  subject_areas:\n    - E\n")

    out = StringIO()
    call_command("find_grants", profile=str(profile), format="table", stdout=out)
    assert "Command Test Grant" in out.getvalue()


@pytest.mark.django_db
def test_call_command_json_output(tmp_path):
    import json as _json

    _make_opp(external_id="g:json_test", title="JSON Grant", subject_areas=["E"])
    profile = tmp_path / "profile.yaml"
    profile.write_text("filters:\n  subject_areas:\n    - E\n")

    out = StringIO()
    call_command("find_grants", profile=str(profile), format="json", stdout=out)
    data = _json.loads(out.getvalue())
    titles = [r["title"] for r in data]
    assert "JSON Grant" in titles


@pytest.mark.django_db
def test_call_command_csv_output(tmp_path):
    _make_opp(external_id="g:csv_test", title="CSV Grant", subject_areas=["E"])
    profile = tmp_path / "profile.yaml"
    profile.write_text("filters:\n  subject_areas:\n    - E\n")

    out = StringIO()
    call_command("find_grants", profile=str(profile), format="csv", stdout=out)
    assert "CSV Grant" in out.getvalue()
    assert "external_id" in out.getvalue()  # header present
