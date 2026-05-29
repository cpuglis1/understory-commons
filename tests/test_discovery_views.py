"""Slice 3 required test: public page reads only published snapshots."""

import datetime

import pytest

from accounts.models import User
from core.models import Organization, Program
from core.services.snapshots import build_draft, publish

MAY = datetime.date(2026, 5, 1)
MAY_END = datetime.date(2026, 5, 31)


@pytest.fixture
def org(db):
    return Organization.objects.create(
        name="Passion for Learning",
        description="Youth literacy nonprofit.",
        location="Washington, DC",
    )


@pytest.fixture
def coordinator(org):
    return User.objects.create_user(
        email="coord@example.com",
        display_name="Matthew Ratz",
        organization=org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def program(org, coordinator):
    return Program.objects.create(
        organization=org,
        name="Tuesday Reading Stars",
        summary="3rd–5th grade literacy.",
        coordinator=coordinator,
    )


# --- test_public_page_reads_only_published ---


@pytest.mark.django_db
def test_published_program_returns_200(program, coordinator, client):
    snap = build_draft(program, MAY, MAY_END)
    publish(snap, coordinator)
    response = client.get(f"/programs/{program.slug}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_draft_only_program_returns_404(program, client):
    build_draft(program, MAY, MAY_END)
    response = client.get(f"/programs/{program.slug}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_no_snapshot_program_returns_404(program, client):
    response = client.get(f"/programs/{program.slug}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_nonexistent_slug_returns_404(client):
    response = client.get("/programs/does-not-exist/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_public_page_shows_program_name(program, coordinator, client):
    snap = build_draft(program, MAY, MAY_END)
    publish(snap, coordinator)
    response = client.get(f"/programs/{program.slug}/")
    assert b"Tuesday Reading Stars" in response.content


@pytest.mark.django_db
def test_public_page_shows_metrics(program, coordinator, client):
    snap = build_draft(program, MAY, MAY_END)
    publish(snap, coordinator)
    response = client.get(f"/programs/{program.slug}/")
    assert b"Sessions held" in response.content
    assert b"Students attending" in response.content


@pytest.mark.django_db
def test_public_page_shows_provenance_badge(program, coordinator, client):
    snap = build_draft(program, MAY, MAY_END)
    publish(snap, coordinator)
    response = client.get(f"/programs/{program.slug}/")
    assert b"derived from logged activity" in response.content


@pytest.mark.django_db
def test_public_page_no_auth_required(program, coordinator, client):
    """Page is accessible to unauthenticated visitors."""
    snap = build_draft(program, MAY, MAY_END)
    publish(snap, coordinator)
    response = client.get(f"/programs/{program.slug}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_cross_program_no_bleed(org, coordinator, client):
    """A different program's slug returns 404 when that program has no snapshot."""
    p2_coord = User.objects.create_user(
        email="coord2@example.com",
        display_name="Other Coord",
        organization=org,
        role=User.COORDINATOR,
    )
    program_a = Program.objects.create(organization=org, name="Program A", coordinator=coordinator)
    program_b = Program.objects.create(organization=org, name="Program B", coordinator=p2_coord)

    snap = build_draft(program_a, MAY, MAY_END)
    publish(snap, coordinator)

    # program_b has no snapshot — must 404
    response = client.get(f"/programs/{program_b.slug}/")
    assert response.status_code == 404
