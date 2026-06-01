import calendar
import csv
import datetime
import uuid
from decimal import Decimal

from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import coordinator_required, facilitator_or_coordinator_required
from accounts.models import User
from core.models import Session
from core.queries import programs_visible_to
from core.services.snapshots import build_draft, current_published, preview_payload, publish

from . import launchpad, pay
from .forms import ProgramCreateForm, ProgramSetupForm, SessionWrapForm
from .models import AttendanceRecord, Enrollment, FacilitatorPayPeriod, Participant
from .queries import enrollment_states, latest_status_by_participant

# V1 statuses surfaced in the session guide — present / absent only (the model also
# carries late/excused; they're not offered until a CBO asks).
_GUIDE_STATUSES = {AttendanceRecord.PRESENT, AttendanceRecord.ABSENT}


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


def _visible_program(request, slug: str):
    return get_object_or_404(programs_visible_to(request.user).filter(is_archived=False), slug=slug)


def _todays_session(program) -> Session:
    """Resolve today's session, creating it on first open. Idempotent: the
    unique (program, scheduled_date) constraint means re-opening never duplicates."""
    session, _ = Session.objects.get_or_create(program=program, scheduled_date=timezone.localdate())
    return session


@facilitator_or_coordinator_required
def attendance_log(request, slug: str):
    """The session guide, step 1: open today's session and take attendance (tap-first).

    GET renders the roster — active above the Inactive (ghosting) divider, all tappable.
    POST commits attendance append-only and idempotently (a record is written only when a
    participant's status is new or changed; the per-render key no-ops a re-submit), then
    advances to the wrap screen. V1 statuses are present/absent only.
    """
    program = _visible_program(request, slug)
    session = _todays_session(program)

    if request.method == "POST":
        _commit_attendance(request, program, session)
        return redirect("attendance:session_wrap", slug=program.slug)

    active, inactive = enrollment_states(program)
    latest = latest_status_by_participant(session)

    def _chip(participant):
        return {
            "participant": participant,
            # neutral (absent) until the human acts; a re-opened session shows saved state
            "present": latest.get(participant.id) == AttendanceRecord.PRESENT,
        }

    return render(
        request,
        "attendance/session_guide.html",
        {
            "program": program,
            "session": session,
            "active": [_chip(p) for p in active],
            "inactive": [_chip(p) for p in inactive],
            "idempotency_key": uuid.uuid4().hex,
        },
    )


def _commit_attendance(request, program, session) -> None:
    """Append present/absent records for changed statuses only (adapts da53963)."""
    key = request.POST.get("idempotency_key", "")
    if (
        key
        and AttendanceRecord.objects.filter(
            session=session, submission_idempotency_key=key
        ).exists()
    ):
        return  # a re-POST (double-tap / refresh / back) writes nothing

    latest = latest_status_by_participant(session)
    enrolled = Participant.objects.filter(
        enrollments__program=program, merged_into__isnull=True
    ).distinct()
    for participant in enrolled:
        status = request.POST.get(f"status_{participant.id}", "")
        if status not in _GUIDE_STATUSES:
            continue
        if latest.get(participant.id) == status:
            continue  # unchanged → no new record (keeps the append-only log meaningful)
        AttendanceRecord.objects.create(
            session=session,
            participant=participant,
            status=status,
            recorded_by=request.user,  # the attestation, decoupled from pay attribution
            source=AttendanceRecord.MANUAL_FORM,
            submission_idempotency_key=key,
        )


@facilitator_or_coordinator_required
def session_add_participant(request, slug: str):
    """+ Add someone: enroll a new first-name participant mid-session (PII: name only)."""
    program = _visible_program(request, slug)
    if request.method == "POST":
        name = request.POST.get("display_name", "").strip()
        if name:
            org = program.organization
            participant = Participant.objects.filter(
                organization=org, merged_into__isnull=True, display_name__iexact=name
            ).first() or Participant.objects.create(organization=org, display_name=name)
            Enrollment.objects.get_or_create(program=program, participant=participant)
    return redirect("attendance:attendance_log", slug=program.slug)


@facilitator_or_coordinator_required
def session_wrap(request, slug: str):
    """The session guide, step 2: the free-text note + Facilitator of Record → Save & close.

    Closing commits ``closed_at`` + the program's default duration (the pay length) and
    stamps the FoR. Idempotent: a re-POST overwrites the same note/FoR and never re-closes
    an already-closed session (no double duration, no clobbered timestamp).
    """
    program = _visible_program(request, slug)
    session = _todays_session(program)

    if request.method == "POST":
        form = SessionWrapForm(request.POST, program=program)
        if form.is_valid():
            session.notes = form.cleaned_data["note"]
            session.facilitator_of_record = form.cleaned_data["facilitator_of_record"]
            if session.closed_at is None:
                session.closed_at = timezone.now()
                session.duration_minutes = program.default_session_length_minutes
            session.save()
            statuses = latest_status_by_participant(session).values()
            present = sum(1 for s in statuses if s == AttendanceRecord.PRESENT)
            messages.success(request, f"Session saved — {present} present · {program.name}.")
            return redirect("attendance:home")
    else:
        default_for = session.facilitator_of_record_id or _default_facilitator_id(
            program, request.user
        )
        form = SessionWrapForm(
            program=program,
            initial={"note": session.notes, "facilitator_of_record": default_for},
        )

    statuses = latest_status_by_participant(session).values()
    return render(
        request,
        "attendance/session_wrap.html",
        {
            "program": program,
            "session": session,
            "form": form,
            "present": sum(1 for s in statuses if s == AttendanceRecord.PRESENT),
            "absent": sum(1 for s in statuses if s == AttendanceRecord.ABSENT),
        },
    )


def _default_facilitator_id(program, user):
    """Pre-fill FoR with the program default, else the logged-in facilitator if assigned."""
    if program.default_facilitator_id:
        return program.default_facilitator_id
    if program.facilitators.filter(pk=user.pk).exists():
        return user.pk
    return None


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


# --------------------------------------------------------------------------- #
# Pay prep (Slice D) — the month-end byproduct. Coordinator-only.
# --------------------------------------------------------------------------- #


def _parse_month(value: str | None) -> datetime.date:
    """Parse ?month=YYYY-MM to a first-of-month date; default to the current month."""
    try:
        return datetime.datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except (TypeError, ValueError):
        return timezone.localdate().replace(day=1)


def _pay_redirect(request):
    month = request.POST.get("month", "")
    url = reverse("attendance:pay_prep")
    return f"{url}?month={month}" if month else url


@coordinator_required
def pay_prep(request):
    """Monthly pay table across the coordinator's programs: sessions × duration × rate
    per Facilitator of Record. ?export=csv streams the figures; the page also drives
    reconcile / approve / mark-paid. Understory stops at the math (no money movement)."""
    programs = list(programs_visible_to(request.user).filter(is_archived=False).order_by("name"))
    month_start, month_end = pay.month_bounds(_parse_month(request.GET.get("month")))
    rows = pay.pay_rows(programs, month_start, month_end)

    if request.GET.get("export") == "csv":
        return _pay_csv(rows, month_start)

    return render(
        request,
        "attendance/pay_prep.html",
        {
            "rows": rows,
            "month_start": month_start,
            "month_value": month_start.strftime("%Y-%m"),
            "prev_month": (month_start - datetime.timedelta(days=1)).strftime("%Y-%m"),
            "next_month": (month_end + datetime.timedelta(days=1)).strftime("%Y-%m"),
            "total_display": pay.dollars(pay.total_cents(rows)),
            "statuses": FacilitatorPayPeriod,
        },
    )


def _pay_csv(rows, month_start) -> HttpResponse:
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="pay-{month_start:%Y-%m}.csv"'
    writer = csv.writer(response)
    writer.writerow(["Facilitator", "Program", "Sessions", "Hours", "Rate", "Amount", "Status"])
    for row in rows:
        writer.writerow(
            [
                row.facilitator.display_name if row.facilitator else "(unassigned)",
                row.program.name,
                row.session_count,
                f"{row.hours:.1f}",
                row.rate_display or "",
                row.amount_display or "",
                row.status if row.payable else (row.flag or row.status),
            ]
        )
    return response


def _pay_period(request):
    """Resolve + scope the (program, facilitator, month) a pay action targets, or 404."""
    program = get_object_or_404(
        programs_visible_to(request.user), pk=request.POST.get("program_id")
    )
    facilitator = get_object_or_404(
        User,
        pk=request.POST.get("facilitator_id"),
        organization=request.user.organization,
        role=User.FACILITATOR,
    )
    period, _ = FacilitatorPayPeriod.objects.get_or_create(
        program=program,
        facilitator=facilitator,
        period_month=_parse_month(request.POST.get("month")),
    )
    return period


@coordinator_required
def pay_approve(request):
    if request.method == "POST":
        period = _pay_period(request)
        period.status = FacilitatorPayPeriod.APPROVED
        period.approved_by = request.user
        period.approved_at = timezone.now()
        period.save()
    return redirect(_pay_redirect(request))


@coordinator_required
def pay_paid(request):
    if request.method == "POST":
        period = _pay_period(request)
        period.status = FacilitatorPayPeriod.PAID
        period.paid_at = timezone.now()
        period.save()
    return redirect(_pay_redirect(request))


@coordinator_required
def pay_adjust(request):
    """Reconcile one session's pay duration (0 = a weather cancellation). Mutable on
    purpose: pay is internal, not a donor-verified metric (ADR D9)."""
    if request.method == "POST":
        session = get_object_or_404(
            Session,
            pk=request.POST.get("session_id"),
            program__in=programs_visible_to(request.user),
        )
        try:
            minutes = int(request.POST.get("duration_minutes", ""))
        except (TypeError, ValueError):
            minutes = None
        if minutes is not None and 0 <= minutes <= 1440:
            session.duration_minutes = minutes
            session.save()
    return redirect(_pay_redirect(request))
