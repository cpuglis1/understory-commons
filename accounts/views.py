from django.contrib.auth import login
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .decorators import coordinator_required
from .forms import FacilitatorCreateForm
from .models import MagicLinkToken, User
from .services import magic_link_url, mint_magic_link


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
    return redirect("attendance:home")


@coordinator_required
def facilitator_new(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = FacilitatorCreateForm(request.POST, coordinator=request.user)
        if form.is_valid():
            facilitator = User.objects.create_user(
                email=form.cleaned_data["email"],
                display_name=form.cleaned_data["display_name"],
                organization=request.user.organization,
                role=User.FACILITATOR,
            )
            for program in form.cleaned_data["programs"]:
                program.facilitators.add(facilitator)
            token = mint_magic_link(user=facilitator, created_by=request.user)
            return render(
                request,
                "accounts/facilitator_link.html",
                {"facilitator": facilitator, "magic_url": magic_link_url(token)},
            )
    else:
        form = FacilitatorCreateForm(coordinator=request.user)

    return render(request, "accounts/facilitator_new.html", {"form": form})


@coordinator_required
def facilitator_detail(request: HttpRequest, pk) -> HttpResponse:
    facilitator = get_object_or_404(
        User,
        pk=pk,
        organization=request.user.organization,
        role=User.FACILITATOR,
    )
    magic_url = None
    if request.method == "POST":
        token = mint_magic_link(user=facilitator, created_by=request.user)
        magic_url = magic_link_url(token)

    return render(
        request,
        "accounts/facilitator_detail.html",
        {"facilitator": facilitator, "magic_url": magic_url},
    )
