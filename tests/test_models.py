import pytest
from django.db import IntegrityError

from accounts.models import User
from core.models import Organization


@pytest.mark.django_db
def test_create_coordinator_user():
    org = Organization.objects.create(name="Test CBO")
    user = User.objects.create_user(
        email="coord@example.com",
        display_name="Test Coordinator",
        organization=org,
        role=User.COORDINATOR,
    )
    assert user.pk is not None
    assert user.email == "coord@example.com"
    assert user.role == User.COORDINATOR
    assert user.organization == org
    assert not user.has_usable_password()
    assert user.is_active
    assert not user.is_staff


@pytest.mark.django_db
def test_create_facilitator_user():
    org = Organization.objects.create(name="Test CBO")
    user = User.objects.create_user(
        email="fac@example.com",
        display_name="Test Facilitator",
        organization=org,
        role=User.FACILITATOR,
    )
    assert user.role == User.FACILITATOR


@pytest.mark.django_db
def test_user_email_unique():
    org = Organization.objects.create(name="Test CBO")
    User.objects.create_user(
        email="dup@example.com",
        display_name="First",
        organization=org,
    )
    with pytest.raises(IntegrityError):
        User.objects.create_user(
            email="dup@example.com",
            display_name="Second",
            organization=org,
        )


def test_create_superuser_raises():
    with pytest.raises(NotImplementedError):
        User.objects.create_superuser(email="su@example.com", display_name="Super")
