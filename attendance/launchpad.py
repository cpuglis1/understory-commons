"""Read-only aggregations for the coordinator home (the launchpad).

These functions read the append-only attendance log and the published-snapshot
record to summarize, per program, what ran recently and what is outstanding —
so the home can route the coordinator into the work in one tap.

PII boundary: nothing here reads a participant's ``display_name``. The launchpad
exposes program-level counts and staff actors (the coordinator's own users)
only. Every number traces to a logged event (``AttendanceRecord`` or a published
``ProfileSnapshot``) — never to a new metric source.
"""

import datetime
from dataclasses import dataclass

from django.db.models import Count, Max, QuerySet

from core.models import ProfileSnapshot, Program, Session
from core.services.snapshots import current_published

from .models import AttendanceRecord

# A program with no attendance logged within this trailing window is flagged
# as needing attention on the home.
STALE_AFTER_DAYS = 7


@dataclass
class ProgramCard:
    """A program's row on the launchpad: enough to decide whether to act."""

    program: Program
    last_attendance_date: datetime.date | None
    published: ProfileSnapshot | None
    needs_attention: bool


@dataclass
class ActivityItem:
    """One entry in the recent-activity strip. ``detail`` is program-level only."""

    kind: str  # "attendance" or "publish"
    when: datetime.datetime
    program_name: str
    actor_name: str
    detail: str


def program_cards(
    programs: QuerySet[Program], today: datetime.date | None = None
) -> list[ProgramCard]:
    """One card per visible program, with its last-attendance date, current
    published state, and whether attendance has lapsed (no session bearing
    attendance within the trailing ``STALE_AFTER_DAYS`` days)."""
    today = today or datetime.date.today()
    cutoff = today - datetime.timedelta(days=STALE_AFTER_DAYS)

    # Most recent session date that bears any attendance record, per program.
    last_dates = {
        row["session__program_id"]: row["last"]
        for row in (
            AttendanceRecord.objects.filter(session__program__in=programs)
            .values("session__program_id")
            .annotate(last=Max("session__scheduled_date"))
        )
    }

    cards: list[ProgramCard] = []
    for program in programs:
        last = last_dates.get(program.id)
        cards.append(
            ProgramCard(
                program=program,
                last_attendance_date=last,
                published=current_published(program),
                needs_attention=last is None or last < cutoff,
            )
        )
    return cards


def recent_activity(programs: QuerySet[Program], limit: int = 10) -> list[ActivityItem]:
    """Merged, time-ordered feed of logged events across *programs*: attendance
    logged (grouped per session, so a batch of records reads as one event) and
    snapshots published. Most recent first, capped at *limit*."""
    items: list[ActivityItem] = []

    # Attendance: one event per session that bears records. The event time is the
    # latest record's recorded_at; the actor is whoever logged that latest record.
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
                    f"Logged attendance for {session.scheduled_date:%b %d} "
                    f"— {n} student{'' if n == 1 else 's'}"
                ),
            )
        )

    # Publishes: one event per published snapshot.
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
                detail=f"Published public profile (v{snap.version})",
            )
        )

    items.sort(key=lambda i: i.when, reverse=True)
    return items[:limit]
