import uuid

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import facilitator_or_coordinator_required
from core.models import Session
from core.queries import programs_visible_to

from .forms import ParticipantForm, SessionForm
from .models import AttendanceRecord, Participant
from .queries import latest_status_by_participant, program_month_stats, session_headcount

VALID_STATUSES = {choice for choice, _ in AttendanceRecord.STATUS_CHOICES}


def _visible_session(request, pk) -> Session:
    """Fetch a session whose program the user may see, else 404."""
    return get_object_or_404(
        Session.objects.select_related("program", "program__organization"),
        pk=pk,
        program__in=programs_visible_to(request.user),
    )


def _active_participants(organization):
    return Participant.objects.filter(organization=organization, merged_into__isnull=True).order_by(
        "display_name"
    )


@facilitator_or_coordinator_required
def dashboard(request: HttpRequest) -> HttpResponse:
    programs = list(programs_visible_to(request.user).filter(is_archived=False))
    cards = [{"program": p, "stats": program_month_stats(p)} for p in programs]
    return render(request, "attendance/dashboard.html", {"cards": cards})


@facilitator_or_coordinator_required
def program_detail(request: HttpRequest, pk) -> HttpResponse:
    program = get_object_or_404(programs_visible_to(request.user), pk=pk)

    if request.method == "POST":
        form = SessionForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            session.program = program
            try:
                with transaction.atomic():
                    session.save()
            except IntegrityError:
                form.add_error(
                    "scheduled_date", "A session already exists for this program on that date."
                )
            else:
                messages.success(request, "Session created.")
                return redirect("attendance:session_detail", pk=session.pk)
    else:
        form = SessionForm()

    sessions = [
        {"session": s, "headcount": session_headcount(s)}
        for s in program.sessions.order_by("-scheduled_date")
    ]
    return render(
        request,
        "attendance/program_detail.html",
        {
            "program": program,
            "form": form,
            "sessions": sessions,
            "stats": program_month_stats(program),
        },
    )


@facilitator_or_coordinator_required
def session_detail(request: HttpRequest, pk) -> HttpResponse:
    session = _visible_session(request, pk)
    org = session.program.organization
    latest = latest_status_by_participant(session)
    participants = [
        {"participant": p, "status": latest.get(p.id, "")} for p in _active_participants(org)
    ]
    return render(
        request,
        "attendance/session_detail.html",
        {
            "session": session,
            "participants": participants,
            "status_choices": AttendanceRecord.STATUS_CHOICES,
            "headcount": session_headcount(session),
            "participant_form": ParticipantForm(),
            "idempotency_key": uuid.uuid4().hex,
        },
    )


@facilitator_or_coordinator_required
def record_attendance(request: HttpRequest, pk) -> HttpResponse:
    if request.method != "POST":
        return redirect("attendance:session_detail", pk=pk)

    session = _visible_session(request, pk)
    org = session.program.organization
    key = request.POST.get("idempotency_key", "")

    # Idempotency: a re-submit (back/refresh) with the same key writes nothing.
    if (
        key
        and AttendanceRecord.objects.filter(
            session=session, submission_idempotency_key=key
        ).exists()
    ):
        messages.info(request, "Attendance already saved.")
        return redirect("attendance:session_detail", pk=session.pk)

    latest = latest_status_by_participant(session)
    written = 0
    for participant in _active_participants(org):
        status = request.POST.get(f"status_{participant.id}", "")
        if status not in VALID_STATUSES:
            continue
        # Only append when the status is new or changed — keeps the log meaningful.
        if latest.get(participant.id) == status:
            continue
        AttendanceRecord.objects.create(
            session=session,
            participant=participant,
            status=status,
            recorded_by=request.user,
            source=AttendanceRecord.MANUAL_FORM,
            submission_idempotency_key=key,
        )
        written += 1

    messages.success(request, f"Recorded attendance for {written} participant(s).")
    return redirect("attendance:session_detail", pk=session.pk)


@facilitator_or_coordinator_required
def participant_create(request: HttpRequest, pk) -> HttpResponse:
    session = _visible_session(request, pk)
    if request.method == "POST":
        form = ParticipantForm(request.POST)
        if form.is_valid():
            participant = form.save(commit=False)
            participant.organization = session.program.organization
            participant.save()
            messages.success(request, f"Added {participant.display_name}.")
    return redirect("attendance:session_detail", pk=session.pk)
