"""Tests for CorpusEvent append-only enforcement."""

import pytest
from django.utils import timezone

from grants_ingest.models import CorpusEvent, CorpusEventType


def _make_event(**kwargs):
    defaults = dict(
        timestamp=timezone.now(),
        event_type=CorpusEventType.SEEN,
        source_id="test_source",
        actor="system:test_v0.1.0",
    )
    defaults.update(kwargs)
    return CorpusEvent.objects.create(**defaults)


@pytest.mark.django_db
def test_corpus_event_create():
    event = _make_event()
    assert CorpusEvent.objects.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_corpus_event_update_raises():
    event = _make_event()
    event.source_id = "other_source"
    with pytest.raises(ValueError, match="append-only"):
        event.save()


@pytest.mark.django_db
def test_corpus_event_multiple_types():
    for et in [CorpusEventType.FUNDER_UPSERTED, CorpusEventType.HISTORICAL_GRANT_RECORDED]:
        _make_event(event_type=et)
    assert CorpusEvent.objects.count() == 2
