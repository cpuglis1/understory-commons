import datetime

import pytest
from django.contrib import messages

from accounts.models import User
from attendance.admin import merge_participants
from attendance.models import AttendanceRecord, Participant
from core.models import Organization, Program, Session


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org")


@pytest.fixture
def coordinator(org):
    return User.objects.create_user(
        email="coord@example.com",
        display_name="Coordinator",
        organization=org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def program(org, coordinator):
    return Program.objects.create(organization=org, name="Program", coordinator=coordinator)


@pytest.fixture
def session(program):
    return Session.objects.create(program=program, scheduled_date=datetime.date(2026, 5, 1))


@pytest.fixture
def participant(org):
    return Participant.objects.create(organization=org, display_name="Alex")


@pytest.fixture
def participant_b(org):
    return Participant.objects.create(organization=org, display_name="Alex B.")


@pytest.fixture
def participant_c(org):
    return Participant.objects.create(organization=org, display_name="Alex C.")


def make_record(session, participant, coordinator, status="present", key=""):
    return AttendanceRecord.objects.create(
        session=session,
        participant=participant,
        status=status,
        recorded_by=coordinator,
        source=AttendanceRecord.MANUAL_FORM,
        submission_idempotency_key=key,
    )


# --- AttendanceRecord append-only ---


@pytest.mark.django_db
def test_attendance_record_can_be_created(session, participant, coordinator):
    record = make_record(session, participant, coordinator)
    assert record.pk is not None
    assert record.recorded_at is not None


@pytest.mark.django_db
def test_attendance_record_cannot_be_updated(session, participant, coordinator):
    record = make_record(session, participant, coordinator)
    record.status = AttendanceRecord.ABSENT
    with pytest.raises(ValueError, match="append-only"):
        record.save()


@pytest.mark.django_db
def test_attendance_record_update_fields_also_blocked(session, participant, coordinator):
    record = make_record(session, participant, coordinator)
    record.status = AttendanceRecord.LATE
    with pytest.raises(ValueError, match="append-only"):
        record.save(update_fields=["status"])


@pytest.mark.django_db
def test_latest_record_pattern(session, participant, coordinator):
    """Correction = new record; reporting takes latest by recorded_at."""
    make_record(session, participant, coordinator, status="present", key="k1")
    make_record(session, participant, coordinator, status="absent", key="k2")
    latest = (
        AttendanceRecord.objects.filter(session=session, participant=participant)
        .order_by("-recorded_at")
        .first()
    )
    assert latest.status == AttendanceRecord.ABSENT


# --- Participant merge ---


class _MockAdmin:
    """Minimal stand-in so merge_participants can call message_user."""

    def __init__(self):
        self.messages = []

    def message_user(self, request, message, level=messages.INFO):
        self.messages.append((level, message))


@pytest.mark.django_db
def test_merge_sets_merged_into(participant, participant_b, participant_c):
    qs = Participant.objects.filter(pk__in=[participant.pk, participant_b.pk, participant_c.pk])
    admin = _MockAdmin()
    merge_participants(admin, request=None, queryset=qs)

    target = Participant.objects.order_by("created_at").first()
    for p in Participant.objects.exclude(pk=target.pk):
        assert p.merged_into == target


@pytest.mark.django_db
def test_merge_requires_at_least_two(participant):
    qs = Participant.objects.filter(pk=participant.pk)
    admin = _MockAdmin()
    merge_participants(admin, request=None, queryset=qs)
    assert any(lvl == messages.ERROR for lvl, _ in admin.messages)
    participant.refresh_from_db()
    assert participant.merged_into is None


@pytest.mark.django_db
def test_merge_blocks_already_merged(participant, participant_b, participant_c):
    participant_b.merged_into = participant
    participant_b.save(update_fields=["merged_into"])

    qs = Participant.objects.filter(pk__in=[participant_b.pk, participant_c.pk])
    admin = _MockAdmin()
    merge_participants(admin, request=None, queryset=qs)

    assert any(lvl == messages.ERROR for lvl, _ in admin.messages)
    participant_c.refresh_from_db()
    assert participant_c.merged_into is None


@pytest.mark.django_db
def test_merge_preserves_attendance_history(session, participant, participant_b, coordinator):
    record = make_record(session, participant, coordinator)
    qs = Participant.objects.filter(pk__in=[participant.pk, participant_b.pk])
    merge_participants(_MockAdmin(), request=None, queryset=qs)

    # AttendanceRecord still points to the original participant
    record.refresh_from_db()
    assert record.participant == participant


@pytest.mark.django_db
def test_active_roster_excludes_merged(org, participant, participant_b):
    participant_b.merged_into = participant
    participant_b.save(update_fields=["merged_into"])

    active = Participant.objects.filter(organization=org, merged_into__isnull=True)
    assert participant in active
    assert participant_b not in active


# --- Participant PII boundary ---


@pytest.mark.django_db
def test_participant_has_no_structured_name_fields(participant):
    assert not hasattr(participant, "first_name")
    assert not hasattr(participant, "last_name")
    assert not hasattr(participant, "email")
    assert not hasattr(participant, "phone")


# --- Verification chain ---


@pytest.mark.django_db
def test_attendance_record_verification_chain(session, participant, coordinator):
    record = make_record(session, participant, coordinator, key="idem-key-1")
    assert record.session == session
    assert record.participant == participant
    assert record.recorded_by == coordinator
    assert record.recorded_at is not None
    assert record.source == AttendanceRecord.MANUAL_FORM
