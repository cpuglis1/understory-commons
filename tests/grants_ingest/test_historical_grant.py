"""Tests for HistoricalGrant idempotency constraint.

EINs use the 99-XXXXXXX reserved prefix.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from grants_ingest.models import Funder, FunderType, HistoricalGrant, RawRecord


@pytest.fixture
def funder(db):
    return Funder.objects.create(
        ein="990000010",
        canonical_name="Synthetic Grant Foundation",
        canonical_name_normalized="synthetic grant foundation",
        funder_type=FunderType.PRIVATE_FOUNDATION,
    )


@pytest.fixture
def raw_record(db):
    return RawRecord.objects.create(
        content_sha="b" * 64,
        fetch_url="https://example.com/filing.xml",
        fetched_at=timezone.now(),
        source_id="irs_990pf",
        mime_type="application/xml",
        content_ref="file:///var/lib/uc-corpus/raw/irs_990pf/bb/bbb.bin",
        http_status=200,
    )


@pytest.mark.django_db
def test_historical_grant_create(funder, raw_record):
    g = HistoricalGrant.objects.create(
        funder=funder,
        funder_ein="990000010",
        tax_year=2023,
        recipient_name_raw="Recipient Org for Synthetic Youth",
        amount=Decimal("25000.00"),
        source_record=raw_record,
    )
    assert HistoricalGrant.objects.filter(pk=g.pk).exists()


@pytest.mark.django_db
def test_historical_grant_idempotency_unique_together(funder, raw_record):
    """Re-parsing the same XML row must not create a duplicate grant."""
    kwargs = dict(
        funder=funder,
        funder_ein="990000010",
        tax_year=2023,
        recipient_name_raw="Recipient Org for Synthetic Youth",
        amount=Decimal("25000.00"),
        source_record=raw_record,
    )
    HistoricalGrant.objects.create(**kwargs)
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        HistoricalGrant.objects.create(**kwargs)


@pytest.mark.django_db
def test_historical_grant_same_recipient_different_year(funder, raw_record):
    """Same recipient + amount but different tax year = two distinct rows."""
    base = dict(
        funder=funder,
        funder_ein="990000010",
        recipient_name_raw="Recipient Org for Synthetic Youth",
        amount=Decimal("25000.00"),
        source_record=raw_record,
    )
    HistoricalGrant.objects.create(**base, tax_year=2022)
    HistoricalGrant.objects.create(**base, tax_year=2023)
    assert HistoricalGrant.objects.filter(funder=funder).count() == 2
