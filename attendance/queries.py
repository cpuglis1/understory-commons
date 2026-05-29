"""Derived-metric queries over the attendance event log.

These are the only functions allowed to produce numeric metrics for
ProfileSnapshot payloads. The snapshot service must call these — it
must never accept coordinator-supplied numbers.
"""

import datetime

from core.models import Program, Session

from .models import AttendanceRecord


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
