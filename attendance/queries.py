"""Derived reads over the attendance event log.

Everything here is *derived* from the append-only ``AttendanceRecord`` log — never
stored, never coordinator-supplied. ``sessions_held`` / ``students_attending`` are the
snapshot metrics (the snapshot service must call these and never accept hand-typed
numbers); the rest serve the coordinator surface (session guide, roster state).
"""

import datetime

from core.models import Program, Session

from .models import AttendanceRecord

# Absent this many of a participant's most-recent records in a program → ghosting.
GHOSTING_THRESHOLD = 3


def sessions_held(program: Program, start: datetime.date, end: datetime.date) -> int:
    """Count sessions for *program* whose scheduled_date falls in [start, end]."""
    return Session.objects.filter(
        program=program,
        scheduled_date__gte=start,
        scheduled_date__lte=end,
    ).count()


def students_attending(program: Program, start: datetime.date, end: datetime.date) -> int:
    """Count distinct participants with at least one present/late record in
    sessions for *program* within [start, end].

    Counts a participant once even if they attended multiple sessions.
    """
    return (
        AttendanceRecord.objects.filter(
            session__program=program,
            session__scheduled_date__gte=start,
            session__scheduled_date__lte=end,
            status__in=[AttendanceRecord.PRESENT, AttendanceRecord.LATE],
        )
        .values("participant_id")
        .distinct()
        .count()
    )


def latest_status_by_participant(session: Session) -> dict:
    """Map participant_id → latest status string for one session.

    Corrections are appended (the model is append-only), so the last record written
    wins. Ordered ascending by recorded_at so the final overwrite is the latest.
    """
    latest: dict = {}
    for rec in session.attendance_records.order_by("recorded_at").values(
        "participant_id", "status"
    ):
        latest[rec["participant_id"]] = rec["status"]
    return latest


def enrollment_states(program: Program) -> tuple[list, list]:
    """Split a program's enrolled participants into (active, inactive), derived.

    Inactive = "ghosting": the participant's ``GHOSTING_THRESHOLD`` most-recent records
    *that exist for them* in this program are all ``absent``. Fewer than that many
    records, or any recent present, → active. This is read from the log, never stored,
    so tapping a ghosting kid present (a new present record) restores them on next read
    (ADR D4). Both lists are ordered by display_name.
    """
    enrolled = list(
        program.enrollments.select_related("participant").order_by("participant__display_name")
    )

    # Latest status per (session, participant), keyed so a correction overwrites.
    records = (
        AttendanceRecord.objects.filter(session__program=program)
        .select_related("session")
        .order_by("recorded_at")
    )
    latest: dict[tuple, tuple] = {}
    for rec in records:
        latest[(rec.session_id, rec.participant_id)] = (
            rec.session.scheduled_date,
            rec.status,
        )

    # Per participant: their dated statuses, most recent first.
    by_participant: dict = {}
    for (_session_id, participant_id), (date, status) in latest.items():
        by_participant.setdefault(participant_id, []).append((date, status))

    inactive_ids: set = set()
    for participant_id, dated in by_participant.items():
        dated.sort(key=lambda ds: ds[0], reverse=True)
        recent = dated[:GHOSTING_THRESHOLD]
        if len(recent) == GHOSTING_THRESHOLD and all(
            status == AttendanceRecord.ABSENT for _date, status in recent
        ):
            inactive_ids.add(participant_id)

    active = [e.participant for e in enrolled if e.participant_id not in inactive_ids]
    inactive = [e.participant for e in enrolled if e.participant_id in inactive_ids]
    return active, inactive
