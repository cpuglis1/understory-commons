"""Tests for Funder, FunderAlias, Program, ProgramAlias registry models.

Synthetic fixtures only. EINs use the 99-XXXXXXX reserved prefix.
"""

import pytest

from grants_ingest.models import Funder, FunderAlias, FunderType, Program, ProgramAlias


def _make_funder(**kwargs) -> Funder:
    defaults = dict(
        canonical_name="Test Foundation for Synthetic Things",
        canonical_name_normalized="test foundation for synthetic things",
        funder_type=FunderType.PRIVATE_FOUNDATION,
    )
    defaults.update(kwargs)
    return Funder.objects.create(**defaults)


@pytest.mark.django_db
def test_funder_create():
    f = _make_funder(ein="990000001")
    assert Funder.objects.filter(pk=f.pk).exists()
    assert f.funder_type == FunderType.PRIVATE_FOUNDATION


@pytest.mark.django_db
def test_funder_ein_unique():
    _make_funder(ein="990000002")
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        _make_funder(ein="990000002")


@pytest.mark.django_db
def test_funder_multiple_null_eins():
    """Multiple Funders with no EIN must coexist (NULL != NULL in SQL)."""
    _make_funder(ein=None)
    _make_funder(ein=None)
    assert Funder.objects.filter(ein__isnull=True).count() == 2


@pytest.mark.django_db
def test_funder_alias_lookup(db):
    f = _make_funder()
    FunderAlias.objects.create(
        funder=f, raw="Synthetic Things Foundation", normalized="synthetic things foundation"
    )
    alias = FunderAlias.objects.get(normalized="synthetic things foundation")
    assert alias.funder == f


@pytest.mark.django_db
def test_funder_alias_unique_together(db):
    f = _make_funder()
    FunderAlias.objects.create(funder=f, raw="Alias One", normalized="alias one")
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        FunderAlias.objects.create(funder=f, raw="Alias One Again", normalized="alias one")


@pytest.mark.django_db
def test_program_create(db):
    f = _make_funder()
    p = Program.objects.create(
        funder=f,
        canonical_name="Youth Literacy Initiative",
        canonical_name_normalized="youth literacy initiative",
    )
    assert Program.objects.filter(pk=p.pk).exists()
    assert p.funder == f


@pytest.mark.django_db
def test_program_alias_lookup(db):
    f = _make_funder()
    p = Program.objects.create(
        funder=f,
        canonical_name="Youth Literacy Initiative",
        canonical_name_normalized="youth literacy initiative",
    )
    ProgramAlias.objects.create(program=p, raw="YLI", normalized="yli")
    assert ProgramAlias.objects.get(normalized="yli").program == p
