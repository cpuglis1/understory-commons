import calendar
import datetime

from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import coordinator_required, facilitator_or_coordinator_required
from core.queries import programs_visible_to
from core.services.snapshots import build_draft, current_published, preview_payload, publish


def _current_month() -> tuple[datetime.date, datetime.date]:
    today = datetime.date.today()
    start = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    end = today.replace(day=last_day)
    return start, end


@facilitator_or_coordinator_required
def program_list(request):
    programs = programs_visible_to(request.user).filter(is_archived=False).order_by("name")
    return render(request, "attendance/program_list.html", {"programs": programs})


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
