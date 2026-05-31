"""Slice 1 model tests: ProfileSnapshot + slug fields."""

import datetime

import pytest

from accounts.models import User
from core.models import Organization, ProfileSnapshot, Program


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Passion for Learning")


@pytest.fixture
def coordinator(org):
    return User.objects.create_user(
        email="coord@example.com",
        display_name="Coordinator",
        organization=org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def program(org, coordinator):
    return Program.objects.create(
        organization=org,
        name="Tuesday Reading Stars",
        coordinator=coordinator,
    )


def _draft(program, version=1):
    return ProfileSnapshot.objects.create(
        program=program,
        version=version,
        status=ProfileSnapshot.DRAFT,
        coverage_start=datetime.date(2026, 5, 1),
        coverage_end=datetime.date(2026, 5, 31),
        payload={},
    )


# --- slug auto-generation ---


@pytest.mark.django_db
def test_org_slug_generated_from_name(org):
    assert org.slug == "passion-for-learning"


@pytest.mark.django_db
def test_program_slug_generated_from_name(program):
    assert program.slug == "tuesday-reading-stars"


@pytest.mark.django_db
def test_org_slug_collision_gets_suffix(org, coordinator):
    org2 = Organization.objects.create(name="Passion for Learning")
    assert org2.slug == "passion-for-learning-2"


@pytest.mark.django_db
def test_program_slug_collision_gets_suffix(org, coordinator):
    p2_coord = User.objects.create_user(
        email="coord2@example.com",
        display_name="Coord 2",
        organization=org,
        role=User.COORDINATOR,
    )
    p1 = Program.objects.create(organization=org, name="Literacy", coordinator=coordinator)
    p2 = Program.objects.create(organization=org, name="Literacy", coordinator=p2_coord)
    assert p1.slug == "literacy"
    assert p2.slug == "literacy-2"


@pytest.mark.django_db
def test_slug_not_regenerated_on_name_change(program):
    original_slug = program.slug
    program.name = "Changed Name"
    program.save()
    program.refresh_from_db()
    assert program.slug == original_slug


# --- ProfileSnapshot model ---


@pytest.mark.django_db
def test_draft_snapshot_can_be_created(program):
    snap = _draft(program)
    assert snap.pk is not None
    assert snap.status == ProfileSnapshot.DRAFT
    assert snap.version == 1


@pytest.mark.django_db
def test_draft_snapshot_can_be_updated(program):
    snap = _draft(program)
    snap.payload = {"program": {"name": "Test"}}
    snap.save()
    snap.refresh_from_db()
    assert snap.payload["program"]["name"] == "Test"


@pytest.mark.django_db
def test_published_snapshot_is_immutable(program, coordinator):
    from django.utils import timezone

    snap = _draft(program)
    snap.status = ProfileSnapshot.PUBLISHED
    snap.published_at = timezone.now()
    snap.published_by = coordinator
    snap.save()

    snap.payload = {"tampered": True}
    with pytest.raises(ValueError, match="immutable once published"):
        snap.save()


@pytest.mark.django_db
def test_withdrawn_snapshot_is_a_new_version(program, coordinator):
    """Withdrawal = a new WITHDRAWN row, not a mutation of the published one."""
    from django.utils import timezone

    published = _draft(program, version=1)
    published.status = ProfileSnapshot.PUBLISHED
    published.published_at = timezone.now()
    published.published_by = coordinator
    published.save()

    withdrawn = ProfileSnapshot.objects.create(
        program=program,
        version=2,
        status=ProfileSnapshot.WITHDRAWN,
        supersedes=published,
        coverage_start=published.coverage_start,
        coverage_end=published.coverage_end,
        payload=published.payload,
    )
    assert withdrawn.pk != published.pk
    assert withdrawn.supersedes == published
    published.refresh_from_db()
    assert published.status == ProfileSnapshot.PUBLISHED


@pytest.mark.django_db
def test_unique_version_per_program_enforced(program):
    from django.db import IntegrityError

    _draft(program, version=1)
    with pytest.raises(IntegrityError):
        _draft(program, version=1)
