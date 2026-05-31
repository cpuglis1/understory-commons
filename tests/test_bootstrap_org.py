import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import MagicLinkToken, User
from core.models import Organization


@pytest.mark.django_db
def test_bootstrap_creates_org_and_coordinator(capsys):
    call_command(
        "bootstrap_org",
        "--org-name=Passion for Learning",
        "--email=matthew@example.com",
        "--name=Matthew Ratz",
    )
    org = Organization.objects.get(name="Passion for Learning")
    user = User.objects.get(email="matthew@example.com")
    assert user.organization == org
    assert user.role == User.COORDINATOR
    assert not user.has_usable_password()


@pytest.mark.django_db
def test_bootstrap_prints_login_url(capsys):
    call_command(
        "bootstrap_org",
        "--org-name=Test Org",
        "--email=coord@example.com",
        "--name=Test Coord",
    )
    out = capsys.readouterr().out
    assert "http" in out
    assert "/auth/magic/" in out


@pytest.mark.django_db
def test_bootstrap_mints_magic_link():
    call_command(
        "bootstrap_org",
        "--org-name=Org A",
        "--email=a@example.com",
        "--name=Coordinator A",
    )
    user = User.objects.get(email="a@example.com")
    token = MagicLinkToken.objects.get(user=user)
    assert token.consumed_at is None
    assert token.created_by == user


@pytest.mark.django_db
def test_bootstrap_rejects_duplicate_email():
    call_command(
        "bootstrap_org",
        "--org-name=Org B",
        "--email=dup@example.com",
        "--name=First",
    )
    with pytest.raises(CommandError, match="already exists"):
        call_command(
            "bootstrap_org",
            "--org-name=Org C",
            "--email=dup@example.com",
            "--name=Second",
        )
