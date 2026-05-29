"""Snapshot build and publish service.

Rules enforced here:
- Numbers are ALWAYS derived from attendance.queries — never accepted from a caller.
- A PUBLISHED snapshot is immutable (enforced by ProfileSnapshot.save()).
- Re-publishing creates a new superseding version, never a mutation.
- The same window over the same immutable log always yields the same payload
  (idempotent derivation).
"""

import datetime

from django.db import transaction
from django.utils import timezone

from attendance import queries as attendance_queries
from core.models import ProfileSnapshot, Program


def build_draft(
    program: Program,
    coverage_start: datetime.date,
    coverage_end: datetime.date,
) -> ProfileSnapshot:
    """Create a DRAFT snapshot deriving all metrics from the attendance log.

    Caller may call this multiple times; each call produces a new draft row.
    The draft is not visible on the public page until publish() is called.
    """
    next_version = _next_version(program)

    sessions = attendance_queries.sessions_held(program, coverage_start, coverage_end)
    students = attendance_queries.students_attending(program, coverage_start, coverage_end)
    window_label = f"{coverage_start}..{coverage_end}"

    payload = _build_payload(
        program, coverage_start, coverage_end, sessions, students, window_label
    )

    return ProfileSnapshot.objects.create(
        program=program,
        version=next_version,
        status=ProfileSnapshot.DRAFT,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        payload=payload,
    )


@transaction.atomic
def publish(snapshot: ProfileSnapshot, published_by) -> ProfileSnapshot:
    """Freeze a DRAFT snapshot and make it the current public version.

    If a PUBLISHED snapshot already exists for this program, the new one
    supersedes it. The old snapshot is never mutated.

    Returns the now-PUBLISHED snapshot.
    """
    if snapshot.status != ProfileSnapshot.DRAFT:
        raise ValueError(f"Only DRAFT snapshots can be published; this one is {snapshot.status!r}.")

    prev_published = _current_published(snapshot.program)

    # Re-derive the payload from the log to ensure numbers are fresh and no
    # client-supplied values have crept in since build_draft was called.
    sessions = attendance_queries.sessions_held(
        snapshot.program, snapshot.coverage_start, snapshot.coverage_end
    )
    students = attendance_queries.students_attending(
        snapshot.program, snapshot.coverage_start, snapshot.coverage_end
    )
    window_label = f"{snapshot.coverage_start}..{snapshot.coverage_end}"

    snapshot.payload = _build_payload(
        snapshot.program,
        snapshot.coverage_start,
        snapshot.coverage_end,
        sessions,
        students,
        window_label,
    )
    snapshot.status = ProfileSnapshot.PUBLISHED
    snapshot.published_at = timezone.now()
    snapshot.published_by = published_by
    snapshot.supersedes = prev_published
    snapshot.save()

    return snapshot


def current_published(program: Program) -> ProfileSnapshot | None:
    """Return the currently-visible published snapshot for *program*, or None."""
    return _current_published(program)


# --- internal helpers ---


def _next_version(program: Program) -> int:
    latest = (
        ProfileSnapshot.objects.filter(program=program)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
    )
    return 1 if latest is None else latest + 1


def _current_published(program: Program) -> ProfileSnapshot | None:
    return (
        ProfileSnapshot.objects.filter(program=program, status=ProfileSnapshot.PUBLISHED)
        .order_by("-version")
        .first()
    )


def _build_payload(
    program: Program,
    coverage_start: datetime.date,
    coverage_end: datetime.date,
    sessions: int,
    students: int,
    window_label: str,
) -> dict:
    return {
        "program": {
            "name": program.name,
            "summary": program.summary,
            "site_label": program.site_label,
        },
        "org": {
            "name": program.organization.name,
            "description": program.organization.description,
            "location": program.organization.location,
        },
        "metrics": [
            {
                "key": "sessions_held",
                "label": "Sessions held",
                "value": sessions,
                "unit": "sessions",
                "provenance": "derived",
                "window": window_label,
            },
            {
                "key": "students_attending",
                "label": "Students attending",
                "value": students,
                "unit": "students",
                "provenance": "derived",
                "window": window_label,
            },
        ],
    }
