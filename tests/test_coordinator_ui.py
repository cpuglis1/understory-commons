import pytest

from accounts.models import MagicLinkToken, User
from core.models import Organization, Program


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Other Org")


@pytest.fixture
def coordinator(org):
    return User.objects.create_user(
        email="coord@example.com",
        display_name="Coordinator",
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
def other_coordinator(other_org):
    return User.objects.create_user(
        email="other_coord@example.com",
        display_name="Other Coordinator",
        organization=other_org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def other_facilitator(other_org, other_coordinator):
    return User.objects.create_user(
        email="other_fac@example.com",
        display_name="Other Facilitator",
        organization=other_org,
        role=User.FACILITATOR,
    )


@pytest.fixture
def program(org, coordinator):
    return Program.objects.create(
        organization=org,
        name="Test Program",
        coordinator=coordinator,
    )


# --- /auth/facilitators/new/ access control ---


@pytest.mark.django_db
def test_facilitator_new_blocks_unauthenticated(client):
    response = client.get("/auth/facilitators/new/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_facilitator_new_blocks_facilitator_role(facilitator, client):
    client.force_login(facilitator)
    response = client.get("/auth/facilitators/new/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_facilitator_new_allows_coordinator(coordinator, client):
    client.force_login(coordinator)
    response = client.get("/auth/facilitators/new/")
    assert response.status_code == 200


# --- facilitator creation ---


@pytest.mark.django_db
def test_create_facilitator_success(coordinator, program, client):
    client.force_login(coordinator)
    response = client.post(
        "/auth/facilitators/new/",
        {
            "display_name": "New Fac",
            "email": "newfac@example.com",
            "programs": [str(program.pk)],
        },
    )
    assert response.status_code == 200
    assert b"newfac@example.com" in response.content or b"New Fac" in response.content
    # magic link URL appears in the response
    assert b"/auth/magic/" in response.content


@pytest.mark.django_db
def test_created_facilitator_in_coordinator_org(coordinator, client):
    client.force_login(coordinator)
    client.post(
        "/auth/facilitators/new/",
        {"display_name": "New Fac", "email": "newfac@example.com"},
    )
    user = User.objects.get(email="newfac@example.com")
    assert user.organization == coordinator.organization
    assert user.role == User.FACILITATOR


@pytest.mark.django_db
def test_created_facilitator_assigned_to_programs(coordinator, program, client):
    client.force_login(coordinator)
    client.post(
        "/auth/facilitators/new/",
        {
            "display_name": "New Fac",
            "email": "newfac@example.com",
            "programs": [str(program.pk)],
        },
    )
    user = User.objects.get(email="newfac@example.com")
    assert program.facilitators.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_create_facilitator_mints_token(coordinator, client):
    client.force_login(coordinator)
    client.post(
        "/auth/facilitators/new/",
        {"display_name": "New Fac", "email": "newfac@example.com"},
    )
    user = User.objects.get(email="newfac@example.com")
    assert MagicLinkToken.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_create_facilitator_duplicate_email_shows_error(coordinator, facilitator, client):
    client.force_login(coordinator)
    response = client.post(
        "/auth/facilitators/new/",
        {"display_name": "Dup", "email": facilitator.email},
    )
    assert response.status_code == 200
    assert b"already exists" in response.content


@pytest.mark.django_db
def test_coordinator_cannot_assign_other_org_program(
    coordinator, other_org, other_coordinator, client
):
    other_program = Program.objects.create(
        organization=other_org,
        name="Other Program",
        coordinator=other_coordinator,
    )
    client.force_login(coordinator)
    response = client.post(
        "/auth/facilitators/new/",
        {
            "display_name": "New Fac",
            "email": "newfac@example.com",
            "programs": [str(other_program.pk)],
        },
    )
    # Form rejects the invalid program choice
    assert response.status_code == 200
    assert not User.objects.filter(email="newfac@example.com").exists()


# --- /auth/facilitators/<pk>/ access control ---


@pytest.mark.django_db
def test_facilitator_detail_blocks_unauthenticated(facilitator, client):
    response = client.get(f"/auth/facilitators/{facilitator.pk}/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_facilitator_detail_blocks_facilitator_role(facilitator, client):
    client.force_login(facilitator)
    response = client.get(f"/auth/facilitators/{facilitator.pk}/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_facilitator_detail_allows_coordinator(coordinator, facilitator, client):
    client.force_login(coordinator)
    response = client.get(f"/auth/facilitators/{facilitator.pk}/")
    assert response.status_code == 200
    assert facilitator.display_name.encode() in response.content


@pytest.mark.django_db
def test_coordinator_cannot_view_other_org_facilitator(coordinator, other_facilitator, client):
    client.force_login(coordinator)
    response = client.get(f"/auth/facilitators/{other_facilitator.pk}/")
    assert response.status_code == 404


# --- re-mint ---


@pytest.mark.django_db
def test_remint_creates_new_token(coordinator, facilitator, client):
    client.force_login(coordinator)
    before = MagicLinkToken.objects.filter(user=facilitator).count()
    response = client.post(f"/auth/facilitators/{facilitator.pk}/")
    assert response.status_code == 200
    assert MagicLinkToken.objects.filter(user=facilitator).count() == before + 1
    assert b"/auth/magic/" in response.content


@pytest.mark.django_db
def test_remint_token_created_by_coordinator(coordinator, facilitator, client):
    client.force_login(coordinator)
    client.post(f"/auth/facilitators/{facilitator.pk}/")
    token = MagicLinkToken.objects.filter(user=facilitator).latest("created_at")
    assert token.created_by == coordinator
