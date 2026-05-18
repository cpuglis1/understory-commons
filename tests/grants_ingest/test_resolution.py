"""Tests for entity resolver: normalization rules, EIN wins, alias match.

Synthetic fixtures only. EINs use the 99-XXXXXXX reserved prefix.
"""

import pytest

from grants_ingest.models import Funder, FunderAlias, FunderType
from grants_ingest.resolution import normalize_funder_name, resolve_funder


def _funder(ein, name):
    normalized = normalize_funder_name(name)
    return Funder.objects.create(
        ein=ein,
        canonical_name=name,
        canonical_name_normalized=normalized,
        funder_type=FunderType.PRIVATE_FOUNDATION,
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalize_strips_suffixes():
    assert normalize_funder_name("The Smith Foundation, Inc.") == "smith"


def test_normalize_collapses_whitespace():
    assert normalize_funder_name("  Youth   Fund  ") == "youth"


def test_normalize_strips_punctuation():
    assert normalize_funder_name("A & B Trust") == "a b"


def test_normalize_lowercases():
    assert normalize_funder_name("JONES FOUNDATION") == "jones"


# ---------------------------------------------------------------------------
# EIN match wins over name match
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ein_match_wins(db):
    f = _funder("990000030", "Synthetic EIN Foundation")
    result = resolve_funder("Completely Different Name", ein="99-0000030")
    assert result.confidence == "ein"
    assert result.funder_id == str(f.id)


@pytest.mark.django_db
def test_ein_with_dash_normalized(db):
    _funder("990000031", "Dash EIN Foundation")
    result = resolve_funder("Dash EIN Foundation", ein="99-0000031")
    assert result.confidence == "ein"


# ---------------------------------------------------------------------------
# Name match
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_canonical_name_match(db):
    f = _funder("990000032", "Youth Education Fund")
    result = resolve_funder("Youth Education Fund")
    assert result.confidence == "name"
    assert result.funder_id == str(f.id)


@pytest.mark.django_db
def test_name_match_after_normalization(db):
    _funder("990000033", "Valley Youth Foundation")
    result = resolve_funder("The Valley Youth Foundation, Inc.")
    assert result.confidence == "name"


# ---------------------------------------------------------------------------
# Alias match
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_alias_match(db):
    f = _funder("990000034", "Community Youth Foundation")
    FunderAlias.objects.create(funder=f, raw="CYF", normalized=normalize_funder_name("CYF"))
    result = resolve_funder("CYF")
    assert result.confidence == "alias"
    assert result.funder_id == str(f.id)


# ---------------------------------------------------------------------------
# Miss
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_miss_returns_none(db):
    result = resolve_funder("Completely Unknown Organization")
    assert result.confidence == "none"
    assert result.funder_id is None
