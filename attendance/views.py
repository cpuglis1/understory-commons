import calendar
import datetime
from decimal import Decimal

from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import coordinator_required, facilitator_or_coordinator_required
from core.queries import programs_visible_to
from core.services.snapshots import build_draft, current_published, preview_payload, publish

from . import launchpad
from .forms import ProgramCreateForm, ProgramSetupForm


def _current_month() -> tuple[datetime.date, datetime.date]:
    today = datetime.date.today()
    start = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    end = today.replace(day=last_day)
    return start, end


@facilitator_or_coordinator_required
def home(request):
    """The director dashboard (command center).

    Reports on the whole org the user may see (role-scoped): verified stat cards
    for the selected period, a needs-attention triage queue, a programs grid, and
    a cross-tool activity feed. Every number traces to a logged event; no
    participant identities appear here.
    """
    programs = list(programs_visible_to(request.user).filter(is_archived=False).order_by("name"))
    period = launchpad.resolve_period(request.GET.get("period"))
    cards = launchpad.program_cards(programs, period)

    attention: list[dict] = []
    for card in cards:
        if card.attendance_stale:
            attention.append(
                {
                    "program": card.program,
                    "detail": "no attendance logged in the last 7 days",
                    "url": reverse("attendance:attendance_log", args=[card.program.slug]),
                    "action": "Log attendance",
                }
            )
    for card in cards:
        if card.profile_stale:
            days = (timezone.now() - card.published.published_at).days
            attention.append(
                {
                    "program": card.program,
                    "detail": f"public profile is {days} days stale",
                    "url": reverse("attendance:program_detail", args=[card.program.slug]),
                    "action": "Re-publish",
                }
            )

    return render(
        request,
        "attendance/home.html",
        {
            "period": period,
            "stats": launchpad.org_stats(programs, period),
            "cards": cards,
            "attention": attention,
            "activity": launchpad.recent_activity(programs),
        },
    )


@facilitator_or_coordinator_required
def attendance_log(request, slug: str):
    """Stub destination for the home's "Log attendance" CTA.

    The real capture screen is slice 2. This page exists so the launchpad's
    primary action is never a dead end: it names what is coming and points to
    the interim path (Django admin) for anyone who must log attendance today.
    """
    program = get_object_or_404(
        programs_visible_to(request.user).filter(is_archived=False), slug=slug
    )
    return render(request, "attendance/attendance_log.html", {"program": program})


@facilitator_or_coordinator_required
def program_list(request):
    programs = programs_visible_to(request.user).filter(is_archived=False).order_by("name")
    return render(request, "attendance/program_list.html", {"programs": programs})


@coordinator_required
def program_new(request):
    if request.method == "POST":
        form = ProgramCreateForm(request.POST)
        if form.is_valid():
            program = form.save(commit=False)
            program.organization = request.user.organization
            program.coordinator = request.user
            program.save()
            return redirect("attendance:program_detail", slug=program.slug)
    else:
        form = ProgramCreateForm()
    return render(request, "attendance/program_new.html", {"form": form})


def _setup_initial(program) -> dict:
    """Initial values for the setup form: current defaults + existing rates (cents→dollars)."""
    initial = {
        "default_session_length_minutes": program.default_session_length_minutes,
        "default_facilitator": program.default_facilitator_id,
    }
    for link in program.facilitator_links.all():
        if link.hourly_rate_cents is not None:
            initial[f"rate_{link.facilitator_id}"] = Decimal(link.hourly_rate_cents) / 100
    return initial


@coordinator_required
def program_setup(request, slug: str):
    """One-time per-program setup (session-guide Slice A): pay defaults, per-facilitator
    rates, and a paste-a-list roster. Coordinator-only; cross-org slug → 404.

    Idempotent save (rates upsert, roster dedupes) + post-redirect-get, so a refresh
    never double-enrolls.
    """
    program = get_object_or_404(
        programs_visible_to(request.user).filter(is_archived=False), slug=slug
    )
    if request.method == "POST":
        form = ProgramSetupForm(request.POST, program=program)
        if form.is_valid():
            added = form.save()
            if added:
                messages.success(
                    request,
                    f"Added {added} student{'' if added == 1 else 's'} to the roster.",
                )
            messages.success(request, "Program setup saved.")
            return redirect("attendance:program_setup", slug=program.slug)
    else:
        form = ProgramSetupForm(program=program, initial=_setup_initial(program))

    roster = program.enrollments.select_related("participant").order_by("participant__display_name")
    return render(
        request,
        "attendance/program_setup.html",
        {"program": program, "form": form, "roster": roster},
    )


@facilitator_or_coordinator_required
def program_detail(request, slug: str):
    program = get_object_or_404(
        programs_visible_to(request.user).filter(is_archived=False), slug=slug
    )
    published = current_published(program)
    coverage_start, coverage_end = _current_month()
    return render(
        request,
        "attendance/program_detail.html",
        {
            "program": program,
            "published": published,
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
        },
    )


@facilitator_or_coordinator_required
def program_preview(request, slug: str):
    program = get_object_or_404(
        programs_visible_to(request.user).filter(is_archived=False), slug=slug
    )
    coverage_start, coverage_end = _current_month()
    payload = preview_payload(program, coverage_start, coverage_end)
    return render(
        request,
        "discovery/program_detail.html",
        {"payload": payload, "is_preview": True},
    )


@coordinator_required
def program_publish(request, slug: str):
    if request.method != "POST":
        return HttpResponseForbidden("POST required.")
    program = get_object_or_404(
        programs_visible_to(request.user).filter(is_archived=False), slug=slug
    )
    coverage_start, coverage_end = _current_month()
    draft = build_draft(program, coverage_start, coverage_end)
    publish(draft, request.user)
    return redirect("attendance:program_detail", slug=slug)
