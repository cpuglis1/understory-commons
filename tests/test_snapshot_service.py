"""Slice 2 required tests: verification chain, PII boundary, append-only, idempotency."""

import datetime
import json

import pytest

from accounts.models import User
from attendance.models import AttendanceRecord, Participant
from attendance.queries import sessions_held, students_attending
from core.models import Organization, ProfileSnapshot, Program, Session
from core.services.snapshots import build_draft, current_published, publish


@pytest.fixture
def org(db):
    return Organization.objects.create(
        name="Passion for Learning",
        description="A great org",
        location="Washington, DC",
    )


@pytest.fixture
def coordinator(org):
    return User.objects.create_user(
        email="coord@example.com",
        display_name="Matthew Ratz",
        organization=org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def program(org, coordinator):
    return Program.objects.create(
        organization=org,
        name="Tuesday Reading Stars",
        summary="Literacy program for 3rd–5th graders.",
        coordinator=coordinator,
    )


MAY = datetime.date(2026, 5, 1)
MAY_END = datetime.date(2026, 5, 31)


def _session(program, date):
    return Session.objects.create(program=program, scheduled_date=date)


def _record(session, participant, coordinator, status=AttendanceRecord.PRESENT):
    return AttendanceRecord.objects.create(
        session=session,
        participant=participant,
        status=status,
        recorded_by=coordinator,
        source=AttendanceRecord.MANUAL_FORM,
    )


def _participant(org, name):
    return Participant.objects.create(organization=org, display_name=name)


# --- test_snapshot_numbers_derive_from_log ---


@pytest.mark.django_db
def test_snapshot_numbers_derive_from_log(org, program, coordinator):
    """Payload metrics must equal what attendance.queries returns for the window."""
    s1 = _session(program, datetime.date(2026, 5, 6))
    s2 = _session(program, datetime.date(2026, 5, 13))
    p1 = _participant(org, "Alice")
    p2 = _participant(org, "Bob")
    p3 = _participant(org, "Carlos")

    _record(s1, p1, coordinator)
    _record(s1, p2, coordinator)
    _record(s2, p1, coordinator)
    _record(s2, p3, coordinator)

    snap = build_draft(program, MAY, MAY_END)
    publish(snap, coordinator)

    expected_sessions = sessions_held(program, MAY, MAY_END)
    expected_students = students_attending(program, MAY, MAY_END)

    metrics = {m["key"]: m["value"] for m in snap.payload["metrics"]}
    assert metrics["sessions_held"] == expected_sessions == 2
    assert metrics["students_attending"] == expected_students == 3


# --- test_snapshot_payload_has_no_pii ---


@pytest.mark.django_db
def test_snapshot_payload_has_no_pii(org, program, coordinator):
    """No participant display_name may appear anywhere in the snapshot payload."""
    names = ["Alice Smith", "Bob Jones", "Carlos Rivera"]
    session = _session(program, datetime.date(2026, 5, 6))
    for name in names:
        p = _participant(org, name)
        _record(session, p, coordinator)

    snap = build_draft(program, MAY, MAY_END)
    publish(snap, coordinator)

    payload_str = json.dumps(snap.payload)
    for name in names:
        assert name not in payload_str, f"PII leak: {name!r} found in payload"
    # Also check first names in case of partial match
    for name in names:
        first = name.split()[0]
        assert first not in payload_str, f"PII leak: first name {first!r} found in payload"


# --- test_published_snapshot_is_immutable (service-layer version) ---


@pytest.mark.django_db
def test_published_snapshot_immutable_via_service(program, coordinator):
    """publish() freezes the snapshot; any subsequent save raises."""
    snap = build_draft(program, MAY, MAY_END)
    publish(snap, coordinator)

    snap.payload = {"tampered": True}
    with pytest.raises(ValueError, match="immutable once published"):
        snap.save()


# --- test_republish_supersedes_not_mutates ---


@pytest.mark.django_db
def test_republish_supersedes_not_mutates(program, coordinator):
    """Re-publishing creates a new version linked via supersedes; old row unchanged."""
    snap_v1 = build_draft(program, MAY, MAY_END)
    publish(snap_v1, coordinator)

    snap_v2 = build_draft(program, MAY, MAY_END)
    publish(snap_v2, coordinator)

    assert snap_v2.version == snap_v1.version + 1
    assert snap_v2.supersedes_id == snap_v1.pk
    assert snap_v2.status == ProfileSnapshot.PUBLISHED

    # v1 is untouched
    snap_v1.refresh_from_db()
    assert snap_v1.status == ProfileSnapshot.PUBLISHED


# --- test_publish_idempotent_same_window ---


@pytest.mark.django_db
def test_publish_idempotent_same_window(org, program, coordinator):
    """Same log + same window → same payload values on every publish."""
    s1 = _session(program, datetime.date(2026, 5, 6))
    p1 = _participant(org, "Alice")
    _record(s1, p1, coordinator)

    snap_a = build_draft(program, MAY, MAY_END)
    publish(snap_a, coordinator)

    snap_b = build_draft(program, MAY, MAY_END)
    publish(snap_b, coordinator)

    metrics_a = {m["key"]: m["value"] for m in snap_a.payload["metrics"]}
    metrics_b = {m["key"]: m["value"] for m in snap_b.payload["metrics"]}
    assert metrics_a == metrics_b


# --- test_public_page_reads_only_published ---
# (The view-level test lives in test_discovery_views.py; here we test the
# current_published() helper that the view delegates to.)


@pytest.mark.django_db
def test_current_published_returns_none_for_draft(program, coordinator):
    build_draft(program, MAY, MAY_END)
    assert current_published(program) is None


@pytest.mark.django_db
def test_current_published_returns_latest_published(program, coordinator):
    snap_v1 = build_draft(program, MAY, MAY_END)
    publish(snap_v1, coordinator)
    snap_v2 = build_draft(program, MAY, MAY_END)
    publish(snap_v2, coordinator)

    result = current_published(program)
    assert result.pk == snap_v2.pk


@pytest.mark.django_db
def test_current_published_none_for_program_with_no_snapshots(program):
    assert current_published(program) is None


# --- publish() guards ---


@pytest.mark.django_db
def test_publish_rejects_already_published_snapshot(program, coordinator):
    snap = build_draft(program, MAY, MAY_END)
    publish(snap, coordinator)
    with pytest.raises(ValueError, match="Only DRAFT"):
        publish(snap, coordinator)


@pytest.mark.django_db
def test_publish_sets_published_at_and_by(program, coordinator):
    snap = build_draft(program, MAY, MAY_END)
    publish(snap, coordinator)
    snap.refresh_from_db()
    assert snap.published_at is not None
    assert snap.published_by == coordinator


@pytest.mark.django_db
def test_build_draft_provenance_fields(program, coordinator):
    snap = build_draft(program, MAY, MAY_END)
    for metric in snap.payload["metrics"]:
        assert metric["provenance"] == "derived"
        assert "window" in metric
