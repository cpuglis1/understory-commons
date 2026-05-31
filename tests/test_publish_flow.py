"""Slice 4: coordinator publish flow (view-level)."""

import pytest

from accounts.models import User
from core.models import Organization, ProfileSnapshot, Program
from core.services.snapshots import current_published


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Passion for Learning")


@pytest.fixture
def coordinator(org):
    return User.objects.create_user(
        email="coord@example.com",
        display_name="Matthew Ratz",
        organization=org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def facilitator(org, coordinator):
    return User.objects.create_user(
        email="fac@example.com",
        display_name="Facilitator",
        organization=org,
        role=User.FACILITATOR,
    )


@pytest.fixture
def other_coordinator(db):
    other_org = Organization.objects.create(name="Other Org")
    return User.objects.create_user(
        email="other@example.com",
        display_name="Other Coord",
        organization=other_org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def program(org, coordinator):
    return Program.objects.create(
        organization=org,
        name="Tuesday Reading Stars",
        coordinator=coordinator,
    )


# --- program_new ---


@pytest.mark.django_db
def test_program_new_blocked_for_facilitator(facilitator, client):
    client.force_login(facilitator)
    response = client.get("/coordinator/programs/new/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_program_new_creates_in_own_org(coordinator, org, client):
    client.force_login(coordinator)
    response = client.post(
        "/coordinator/programs/new/",
        {"name": "Wednesday Math Club", "summary": "", "site_label": ""},
    )
    assert response.status_code == 302
    created = Program.objects.get(name="Wednesday Math Club")
    assert created.organization == org
    assert created.coordinator == coordinator
    assert created.slug  # auto-generated
    assert response.url == f"/coordinator/programs/{created.slug}/"


# --- program_list ---


@pytest.mark.django_db
def test_program_list_requires_auth(client):
    response = client.get("/coordinator/programs/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_program_list_shows_programs(coordinator, program, client):
    client.force_login(coordinator)
    response = client.get("/coordinator/programs/")
    assert response.status_code == 200
    assert b"Tuesday Reading Stars" in response.content


# --- program_detail ---


@pytest.mark.django_db
def test_program_detail_requires_auth(program, client):
    response = client.get(f"/coordinator/programs/{program.slug}/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_program_detail_shows_unpublished_state(coordinator, program, client):
    client.force_login(coordinator)
    response = client.get(f"/coordinator/programs/{program.slug}/")
    assert response.status_code == 200
    assert b"No published profile yet" in response.content


@pytest.mark.django_db
def test_program_detail_404_for_other_org(coordinator, other_coordinator, program, client):
    client.force_login(other_coordinator)
    response = client.get(f"/coordinator/programs/{program.slug}/")
    assert response.status_code == 404


# --- publish POST ---


@pytest.mark.django_db
def test_publish_creates_published_snapshot(coordinator, program, client):
    client.force_login(coordinator)
    response = client.post(f"/coordinator/programs/{program.slug}/publish/")
    assert response.status_code == 302
    snap = current_published(program)
    assert snap is not None
    assert snap.status == ProfileSnapshot.PUBLISHED
    assert snap.published_by == coordinator


@pytest.mark.django_db
def test_publish_blocked_for_facilitator(facilitator, program, client):
    client.force_login(facilitator)
    response = client.post(f"/coordinator/programs/{program.slug}/publish/")
    assert response.status_code == 403
    assert current_published(program) is None


@pytest.mark.django_db
def test_publish_blocked_for_unauthenticated(program, client):
    response = client.post(f"/coordinator/programs/{program.slug}/publish/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_republish_creates_superseding_version(coordinator, program, client):
    client.force_login(coordinator)
    client.post(f"/coordinator/programs/{program.slug}/publish/")
    client.post(f"/coordinator/programs/{program.slug}/publish/")
    snaps = list(
        ProfileSnapshot.objects.filter(program=program, status=ProfileSnapshot.PUBLISHED).order_by(
            "version"
        )
    )
    assert len(snaps) == 2
    assert snaps[1].supersedes_id == snaps[0].pk


@pytest.mark.django_db
def test_publish_redirects_to_program_detail(coordinator, program, client):
    client.force_login(coordinator)
    response = client.post(f"/coordinator/programs/{program.slug}/publish/")
    assert response.url == f"/coordinator/programs/{program.slug}/"


# --- preview ---


@pytest.mark.django_db
def test_preview_returns_200(coordinator, program, client):
    client.force_login(coordinator)
    response = client.get(f"/coordinator/programs/{program.slug}/preview/")
    assert response.status_code == 200
    assert b"Sessions held" in response.content


@pytest.mark.django_db
def test_preview_does_not_publish(coordinator, program, client):
    client.force_login(coordinator)
    client.get(f"/coordinator/programs/{program.slug}/preview/")
    assert current_published(program) is None


# --- detail shows published state after publish ---


@pytest.mark.django_db
def test_program_detail_shows_published_state(coordinator, program, client):
    client.force_login(coordinator)
    client.post(f"/coordinator/programs/{program.slug}/publish/")
    response = client.get(f"/coordinator/programs/{program.slug}/")
    assert b"Last published" in response.content
    assert b"View public page" in response.content
