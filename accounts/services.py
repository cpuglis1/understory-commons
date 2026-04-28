import secrets
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import MagicLinkToken, User


def mint_magic_link(user: User, created_by: User) -> MagicLinkToken:
    return MagicLinkToken.objects.create(
        user=user,
        token=secrets.token_urlsafe(48),
        expires_at=timezone.now() + timedelta(days=7),
        created_by=created_by,
    )


def magic_link_url(token: MagicLinkToken) -> str:
    path = reverse("accounts:magic_login", args=[token.token])
    return f"{settings.SITE_URL}{path}"
