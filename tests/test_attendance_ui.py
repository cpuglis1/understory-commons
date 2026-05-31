"""Tests for the coordinator attendance UI (dashboard → session → record).

Covers access control, org/role scoping, session-create idempotency, the
append-only attendance write path, and the PII boundary on participant create.
"""

import datetime

import pytest

from accounts.models import User
from attendance.models import AttendanceRecord, Participant
from core.models import Organization, Program, Session


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Other Org")


@pytest.fixture
def coordinator(org):
    return User.objects.create_user(
        email="coord@example.com", display_name="Coord", organization=org, role=User.COORDINATOR
    )


@pytest.fixture
def facilitator(org):
    return User.objects.create_user(
        email="fac@example.com", display_name="Fac", organization=org, role=User.FACILITATOR
    )


@pytest.fixture
def other_coordinator(other_org):
    return User.objects.create_user(
        email="oc@example.com", display_name="OC", organization=other_org, role=User.COORDINATOR
    )


@pytest.fixture
def program(org, coordinator):
    return Program.objects.create(organization=org, name="Reading Stars", coordinator=coordinator)


@pytest.fixture
def other_program(other_org, other_coordinator):
    return Program.objects.create(
        organization=other_org, name="Other Prog", coordinator=other_coordinator
    )


@pytest.fixture
def session(program):
    return Session.objects.create(program=program, scheduled_date=datetime.date(2026, 5, 1))


@pytest.fixture
def participant(org):
    return Participant.objects.create(organization=org, display_name="Alex")


# --- dashboard access + scoping ---


@pytest.mark.django_db
def test_dashboard_blocks_unauthenticated(client):
    assert client.get("/").status_code == 403


@pytest.mark.django_db
def test_dashboard_shows_coordinator_programs(coordinator, program, client):
    client.force_login(coordinator)
    response = client.get("/")
    assert response.status_code == 200
    assert b"Reading Stars" in response.content


@pytest.mark.django_db
def test_dashboard_facilitator_sees_only_assigned(facilitator, program, client):
    client.force_login(facilitator)
    # Not assigned yet → program hidden
    assert b"Reading Stars" not in client.get("/").content
    program.facilitators.add(facilitator)
    assert b"Reading Stars" in client.get("/").content


@pytest.mark.django_db
def test_dashboard_excludes_other_org_program(coordinator, other_program, client):
    client.force_login(coordinator)
    assert b"Other Prog" not in client.get("/").content


# --- program detail scoping + session creation ---


@pytest.mark.django_db
def test_program_detail_other_org_404(coordinator, other_program, client):
    client.force_login(coordinator)
    assert client.get(f"/programs/{other_program.pk}/").status_code == 404


@pytest.mark.django_db
def test_create_session_success(coordinator, program, client):
    client.force_login(coordinator)
    response = client.post(
        f"/programs/{program.pk}/", {"scheduled_date": "2026-05-08", "notes": "Reading circle"}
    )
    assert response.status_code == 302
    assert Session.objects.filter(program=program, scheduled_date="2026-05-08").exists()


@pytest.mark.django_db
def test_create_session_duplicate_date_rejected(coordinator, program, session, client):
    client.force_login(coordinator)
    response = client.post(
        f"/programs/{program.pk}/", {"scheduled_date": "2026-05-01", "notes": ""}
    )
    assert response.status_code == 200
    assert b"already exists" in response.content
    assert Session.objects.filter(program=program, scheduled_date="2026-05-01").count() == 1


# --- session detail scoping ---


@pytest.mark.django_db
def test_session_detail_renders_with_participant(coordinator, session, participant, client):
    client.force_login(coordinator)
    response = client.get(f"/sessions/{session.pk}/")
    assert response.status_code == 200
    assert participant.display_name.encode() in response.content
    assert b"Save attendance" in response.content


@pytest.mark.django_db
def test_session_detail_other_org_404(coordinator, other_program, client):
    other_session = Session.objects.create(
        program=other_program, scheduled_date=datetime.date(2026, 5, 2)
    )
    client.force_login(coordinator)
    assert client.get(f"/sessions/{other_session.pk}/").status_code == 404


# --- record attendance: verification chain + idempotency ---


@pytest.mark.django_db
def test_record_attendance_writes_record(coordinator, session, participant, client):
    client.force_login(coordinator)
    response = client.post(
        f"/sessions/{session.pk}/attendance/",
        {"idempotency_key": "key-1", f"status_{participant.id}": "present"},
    )
    assert response.status_code == 302
    record = AttendanceRecord.objects.get(session=session, participant=participant)
    assert record.status == "present"
    assert record.recorded_by == coordinator
    assert record.source == AttendanceRecord.MANUAL_FORM
    assert record.submission_idempotency_key == "key-1"


@pytest.mark.django_db
def test_record_attendance_idempotent_on_resubmit(coordinator, session, participant, client):
    client.force_login(coordinator)
    payload = {"idempotency_key": "key-dup", f"status_{participant.id}": "present"}
    client.post(f"/sessions/{session.pk}/attendance/", payload)
    client.post(f"/sessions/{session.pk}/attendance/", payload)
    assert AttendanceRecord.objects.filter(session=session, participant=participant).count() == 1


@pytest.mark.django_db
def test_record_attendance_unchanged_status_writes_nothing(
    coordinator, session, participant, client
):
    client.force_login(coordinator)
    client.post(
        f"/sessions/{session.pk}/attendance/",
        {"idempotency_key": "k1", f"status_{participant.id}": "present"},
    )
    # Same status, new key → no new append (status unchanged).
    client.post(
        f"/sessions/{session.pk}/attendance/",
        {"idempotency_key": "k2", f"status_{participant.id}": "present"},
    )
    assert AttendanceRecord.objects.filter(session=session, participant=participant).count() == 1


@pytest.mark.django_db
def test_record_attendance_change_appends_new_record(coordinator, session, participant, client):
    client.force_login(coordinator)
    client.post(
        f"/sessions/{session.pk}/attendance/",
        {"idempotency_key": "k1", f"status_{participant.id}": "present"},
    )
    client.post(
        f"/sessions/{session.pk}/attendance/",
        {"idempotency_key": "k2", f"status_{participant.id}": "absent"},
    )
    records = AttendanceRecord.objects.filter(session=session, participant=participant)
    assert records.count() == 2
    assert records.order_by("-recorded_at").first().status == "absent"


@pytest.mark.django_db
def test_record_attendance_blocks_other_org_session(coordinator, other_program, client):
    other_session = Session.objects.create(
        program=other_program, scheduled_date=datetime.date(2026, 5, 3)
    )
    client.force_login(coordinator)
    response = client.post(f"/sessions/{other_session.pk}/attendance/", {"idempotency_key": "x"})
    assert response.status_code == 404


# --- participant create: org scoping + PII boundary ---


@pytest.mark.django_db
def test_participant_create_in_session_org(coordinator, session, client):
    client.force_login(coordinator)
    response = client.post(f"/sessions/{session.pk}/participants/", {"display_name": "Jordan"})
    assert response.status_code == 302
    p = Participant.objects.get(display_name="Jordan")
    assert p.organization == session.program.organization


@pytest.mark.django_db
def test_participant_form_has_no_pii_fields(coordinator, session, client):
    from attendance.forms import ParticipantForm

    assert set(ParticipantForm().fields) == {"display_name"}
