"""Read-only aggregations for the coordinator dashboard (the command center).

These functions read the append-only attendance log and the published-snapshot
record to summarize, for the whole org and per program, what ran in a period and
what is outstanding — so the director's home reports on the platform at a glance.

PII boundary: nothing here reads a participant's ``display_name``. The dashboard
exposes org/program-level counts, rates, and statuses plus staff actors (the
director's own users) only. Every number traces to a logged event (an
``AttendanceRecord`` or a published ``ProfileSnapshot``) — never a new metric
source, never a coordinator-supplied figure.
"""

import datetime
from dataclasses import dataclass

from django.db.models import Count, Max, QuerySet
from django.utils import timezone

from core.models import ProfileSnapshot, Program, Session
from core.services.snapshots import current_published

from .models import AttendanceRecord

# A program with no attendance logged within this trailing window needs attention.
ATTENDANCE_STALE_DAYS = 7
# A published profile older than this is flagged as going stale.
PROFILE_STALE_DAYS = 21

_PRESENT = [AttendanceRecord.PRESENT, AttendanceRecord.LATE]


# --------------------------------------------------------------------------- #
# Period windows
# --------------------------------------------------------------------------- #


@dataclass
class Period:
    key: str  # "week" | "month" | "all"
    label: str
    start: datetime.date
    end: datetime.date


def resolve_period(key: str | None, today: datetime.date | None = None) -> Period:
    """Map a ``?period=`` value to a concrete [start, end] window (end = today)."""
    today = today or datetime.date.today()
    key = key if key in ("week", "month", "all") else "month"
    if key == "week":
        return Period("week", "This week", today - datetime.timedelta(days=6), today)
    if key == "all":
        return Period("all", "All time", datetime.date(1900, 1, 1), today)
    return Period("month", "This month", today.replace(day=1), today)


# --------------------------------------------------------------------------- #
# Org-level stat cards
# --------------------------------------------------------------------------- #


@dataclass
class OrgStats:
    active_programs: int
    students_reached: int
    sessions_held: int
    attendance_rate: float | None  # 0..1, or None when no records in window
    profiles_live: int


def org_stats(programs: QuerySet[Program] | list[Program], period: Period) -> OrgStats:
    """Verified org rollups across *programs* for the period's window."""
    in_window = {
        "session__program__in": programs,
        "session__scheduled_date__gte": period.start,
        "session__scheduled_date__lte": period.end,
    }
    records = AttendanceRecord.objects.filter(**in_window)
    total = records.count()
    present = records.filter(status__in=_PRESENT).count()

    students = records.filter(status__in=_PRESENT).values("participant_id").distinct().count()
    sessions = Session.objects.filter(
        program__in=programs,
        scheduled_date__gte=period.start,
        scheduled_date__lte=period.end,
    ).count()
    profiles_live = sum(1 for p in programs if current_published(p) is not None)

    return OrgStats(
        active_programs=len(programs),
        students_reached=students,
        sessions_held=sessions,
        attendance_rate=(present / total) if total else None,
        profiles_live=profiles_live,
    )


# --------------------------------------------------------------------------- #
# Per-program cards
# --------------------------------------------------------------------------- #


@dataclass
class ProgramCard:
    program: Program
    sessions: int  # in the selected period
    attendance_rate: float | None  # in the selected period
    last_attendance_date: datetime.date | None  # all-time, for staleness
    published: ProfileSnapshot | None
    attendance_stale: bool  # no attendance in the trailing ATTENDANCE_STALE_DAYS
    profile_stale: bool  # published profile older than PROFILE_STALE_DAYS


def program_cards(
    programs: QuerySet[Program] | list[Program],
    period: Period,
    today: datetime.date | None = None,
) -> list[ProgramCard]:
    """One card per program: period sessions + attendance rate, last-attendance
    date, current publish state, and the two staleness flags."""
    today = today or datetime.date.today()
    attn_cutoff = today - datetime.timedelta(days=ATTENDANCE_STALE_DAYS)
    profile_cutoff = timezone.now() - datetime.timedelta(days=PROFILE_STALE_DAYS)

    cards: list[ProgramCard] = []
    for program in programs:
        window = AttendanceRecord.objects.filter(
            session__program=program,
            session__scheduled_date__gte=period.start,
            session__scheduled_date__lte=period.end,
        )
        total = window.count()
        present = window.filter(status__in=_PRESENT).count()

        sessions = Session.objects.filter(
            program=program,
            scheduled_date__gte=period.start,
            scheduled_date__lte=period.end,
        ).count()

        last = (
            AttendanceRecord.objects.filter(session__program=program)
            .order_by("-session__scheduled_date")
            .values_list("session__scheduled_date", flat=True)
            .first()
        )
        published = current_published(program)

        cards.append(
            ProgramCard(
                program=program,
                sessions=sessions,
                attendance_rate=(present / total) if total else None,
                last_attendance_date=last,
                published=published,
                attendance_stale=last is None or last < attn_cutoff,
                profile_stale=published is not None and published.published_at < profile_cutoff,
            )
        )
    return cards


# --------------------------------------------------------------------------- #
# Cross-tool activity feed
# --------------------------------------------------------------------------- #


@dataclass
class ActivityItem:
    kind: str  # "attendance" or "publish"
    when: datetime.datetime
    program_name: str
    actor_name: str
    detail: str


def recent_activity(
    programs: QuerySet[Program] | list[Program], limit: int = 8
) -> list[ActivityItem]:
    """Merged, time-ordered feed of logged events across *programs*: attendance
    logged (grouped per session, so a batch of records reads as one event) and
    snapshots published. Most recent first, capped at *limit*."""
    items: list[ActivityItem] = []

    sessions = (
        Session.objects.filter(program__in=programs, attendance_records__isnull=False)
        .select_related("program")
        .annotate(
            last_recorded=Max("attendance_records__recorded_at"),
            n_participants=Count("attendance_records__participant", distinct=True),
        )
        .order_by("-last_recorded")[:limit]
    )
    for session in sessions:
        latest = session.attendance_records.select_related("recorded_by").latest("recorded_at")
        n = session.n_participants
        items.append(
            ActivityItem(
                kind="attendance",
                when=session.last_recorded,
                program_name=session.program.name,
                actor_name=latest.recorded_by.display_name,
                detail=(
                    f"Attendance logged — {session.scheduled_date:%b %d} "
                    f"· {n} student{'' if n == 1 else 's'}"
                ),
            )
        )

    publishes = (
        ProfileSnapshot.objects.filter(program__in=programs, status=ProfileSnapshot.PUBLISHED)
        .select_related("program", "published_by")
        .order_by("-published_at")[:limit]
    )
    for snap in publishes:
        items.append(
            ActivityItem(
                kind="publish",
                when=snap.published_at,
                program_name=snap.program.name,
                actor_name=snap.published_by.display_name if snap.published_by else "—",
                detail=f"Public profile published (v{snap.version})",
            )
        )

    items.sort(key=lambda i: i.when, reverse=True)
    return items[:limit]
