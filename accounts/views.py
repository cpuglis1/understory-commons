from django.contrib.auth import login
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from .models import MagicLinkToken


def magic_login(request: HttpRequest, token: str) -> HttpResponse:
    try:
        with transaction.atomic():
            magic_token = MagicLinkToken.objects.select_for_update().get(token=token)
            if magic_token.expires_at < timezone.now() or magic_token.consumed_at is not None:
                return HttpResponse(
                    "This link has expired or has already been used.",
                    status=403,
                    content_type="text/plain",
                )
            magic_token.consumed_at = timezone.now()
            magic_token.save(update_fields=["consumed_at"])
    except MagicLinkToken.DoesNotExist:
        return HttpResponse("Link not found.", status=404, content_type="text/plain")

    login(request, magic_token.user, backend="accounts.backends.MagicLinkBackend")
    return redirect("/")
