from datetime import timedelta

import pytest
from django.contrib.auth import SESSION_KEY
from django.utils import timezone

from accounts.models import MagicLinkToken, User
from accounts.services import magic_link_url, mint_magic_link
from core.models import Organization


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Auth Test Org")


@pytest.fixture
def coordinator(org):
    return User.objects.create_user(
        email="coord@example.com",
        display_name="Coordinator",
        organization=org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def facilitator(org):
    return User.objects.create_user(
        email="fac@example.com",
        display_name="Facilitator",
        organization=org,
        role=User.FACILITATOR,
    )


# --- mint_magic_link ---


@pytest.mark.django_db
def test_mint_creates_token(coordinator):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    assert token.pk is not None
    assert len(token.token) > 0
    assert token.consumed_at is None
    assert token.expires_at > timezone.now()
    assert token.user == coordinator
    assert token.created_by == coordinator


@pytest.mark.django_db
def test_mint_token_urlsafe_length(coordinator):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    assert len(token.token) == 64


@pytest.mark.django_db
def test_mint_expiry_is_seven_days(coordinator):
    before = timezone.now()
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    after = timezone.now()
    assert (
        before + timedelta(days=6, hours=23)
        < token.expires_at
        < after + timedelta(days=7, seconds=5)
    )


@pytest.mark.django_db
def test_magic_link_url_contains_token(coordinator):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    url = magic_link_url(token)
    assert token.token in url
    assert "/auth/magic/" in url


# --- magic_login view ---


@pytest.mark.django_db
def test_valid_token_logs_in_and_redirects(coordinator, client):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    path = f"/auth/magic/{token.token}/"
    response = client.get(path)
    assert response.status_code == 302
    assert response.url == "/coordinator/programs/"
    assert SESSION_KEY in client.session
    assert client.session[SESSION_KEY] == str(coordinator.pk)


@pytest.mark.django_db
def test_valid_token_sets_consumed_at(coordinator, client):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    client.get(f"/auth/magic/{token.token}/")
    token.refresh_from_db()
    assert token.consumed_at is not None


@pytest.mark.django_db
def test_expired_token_returns_403(coordinator, client):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    MagicLinkToken.objects.filter(pk=token.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    response = client.get(f"/auth/magic/{token.token}/")
    assert response.status_code == 403
    assert SESSION_KEY not in client.session


@pytest.mark.django_db
def test_double_consume_returns_403(coordinator, client):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    path = f"/auth/magic/{token.token}/"
    client.get(path)
    client.logout()
    response = client.get(path)
    assert response.status_code == 403


@pytest.mark.django_db
def test_nonexistent_token_returns_404(client):
    response = client.get("/auth/magic/doesnotexist/")
    assert response.status_code == 404


# --- append-only enforcement ---


@pytest.mark.django_db
def test_magic_link_token_append_only(coordinator):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    token.token = "tampered"
    with pytest.raises(ValueError, match="append-only"):
        token.save()


@pytest.mark.django_db
def test_magic_link_token_consumed_at_update_allowed(coordinator):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    token.consumed_at = timezone.now()
    token.save(update_fields=["consumed_at"])
    token.refresh_from_db()
    assert token.consumed_at is not None


# --- role groups ---


@pytest.mark.django_db
def test_coordinator_added_to_coordinators_group(coordinator):
    assert coordinator.groups.filter(name="Coordinators").exists()


@pytest.mark.django_db
def test_facilitator_added_to_facilitators_group(facilitator):
    assert facilitator.groups.filter(name="Facilitators").exists()


# --- role decorators ---


@pytest.mark.django_db
def test_coordinator_required_blocks_unauthenticated(client):
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    from accounts.decorators import coordinator_required

    rf = RequestFactory()
    request = rf.get("/fake/")
    request.user = AnonymousUser()

    @coordinator_required
    def fake_view(request):
        return None

    response = fake_view(request)
    assert response.status_code == 403


@pytest.mark.django_db
def test_coordinator_required_blocks_facilitator(facilitator):
    from django.test import RequestFactory

    from accounts.decorators import coordinator_required

    rf = RequestFactory()
    request = rf.get("/fake/")
    request.user = facilitator

    @coordinator_required
    def fake_view(request):
        return None

    response = fake_view(request)
    assert response.status_code == 403


@pytest.mark.django_db
def test_coordinator_required_passes_coordinator(coordinator):
    from django.http import HttpResponse
    from django.test import RequestFactory

    from accounts.decorators import coordinator_required

    rf = RequestFactory()
    request = rf.get("/fake/")
    request.user = coordinator

    @coordinator_required
    def fake_view(request):
        return HttpResponse("ok")

    response = fake_view(request)
    assert response.status_code == 200
