"""Read-side helpers for the coordinator attendance surface.

Headcount is a *derived* metric: it is computed from the append-only
AttendanceRecord log, never stored. For each (session, participant) we take
the latest record by recorded_at — corrections are new records, so the latest
one wins (see AttendanceRecord docstring). This keeps the verification chain
intact: every number here traces back to a recorded_by/recorded_at event.
"""

from __future__ import annotations

from django.utils import timezone

from .models import AttendanceRecord

PRESENT_STATUSES = (AttendanceRecord.PRESENT, AttendanceRecord.LATE)


def latest_status_by_participant(session) -> dict:
    """Map participant_id -> latest status string for one session.

    Ordered ascending by recorded_at so the last row written wins.
    """
    latest: dict = {}
    for rec in session.attendance_records.order_by("recorded_at").values(
        "participant_id", "status"
    ):
        latest[rec["participant_id"]] = rec["status"]
    return latest


def session_headcount(session) -> int:
    """Count participants whose latest status is present or late."""
    statuses = latest_status_by_participant(session)
    return sum(1 for status in statuses.values() if status in PRESENT_STATUSES)


def program_month_stats(program, on_date=None) -> dict:
    """Sessions held and total present for `program` in the month of `on_date`.

    Defaults to the current local month. Used for the at-a-glance dashboard
    tally the coordinator otherwise keeps in a spreadsheet.
    """
    on_date = on_date or timezone.localdate()
    sessions = program.sessions.filter(
        scheduled_date__year=on_date.year,
        scheduled_date__month=on_date.month,
    )
    return {
        "session_count": sessions.count(),
        "total_present": sum(session_headcount(s) for s in sessions),
    }
