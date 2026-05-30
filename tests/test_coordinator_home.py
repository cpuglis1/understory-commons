"""Slice 1: coordinator home / launchpad.

Required-before-merge coverage from docs/plans/2026-05-30-coordinator-surface.md:
- home requires auth
- role scoping (coordinator sees org; facilitator sees assigned)
- recent-activity feed shows a real attendance event and a real publish event,
  and fabricates nothing when there is no activity
- no participant display_name leaks onto the home
- login redirect lands on the new home
"""

import datetime

import pytest

from accounts.models import User
from accounts.services import mint_magic_link
from attendance import launchpad
from attendance.models import AttendanceRecord, Participant
from core.models import Organization, Program, Session
from core.services.snapshots import build_draft, publish

HOME = "/coordinator/"

# A deliberately distinctive participant name so a PII leak would be unmistakable.
SECRET_NAME = "Zebulon Hiddenkid"


# --- fixtures ---


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Passion for Learning")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Other Org")


@pytest.fixture
def coordinator(org):
    return User.objects.create_user(
        email="coord@example.com",
        display_name="Matthew Ratz",
        organization=org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def facilitator(org, coordinator):
    return User.objects.create_user(
        email="fac@example.com",
        display_name="Facilitator Fran",
        organization=org,
        role=User.FACILITATOR,
    )


@pytest.fixture
def other_coordinator(other_org):
    return User.objects.create_user(
        email="other@example.com",
        display_name="Other Coord",
        organization=other_org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def program(org, coordinator):
    return Program.objects.create(
        organization=org, name="Tuesday Reading Stars", coordinator=coordinator
    )


@pytest.fixture
def program_two(org, coordinator):
    return Program.objects.create(
        organization=org, name="Wednesday Math Club", coordinator=coordinator
    )


@pytest.fixture
def other_program(other_org, other_coordinator):
    return Program.objects.create(
        organization=other_org, name="Far Away Program", coordinator=other_coordinator
    )


def _log_attendance(program, recorder, on_date, name=SECRET_NAME):
    """Append one real attendance record on *on_date* — the verification-chain event."""
    participant = Participant.objects.create(organization=program.organization, display_name=name)
    session = Session.objects.create(program=program, scheduled_date=on_date)
    AttendanceRecord.objects.create(
        session=session,
        participant=participant,
        status=AttendanceRecord.PRESENT,
        recorded_by=recorder,
        source=AttendanceRecord.MANUAL_FORM,
    )
    return session


# --- auth ---


@pytest.mark.django_db
def test_home_requires_auth(client):
    response = client.get(HOME)
    assert response.status_code == 403


@pytest.mark.django_db
def test_home_renders_for_coordinator(coordinator, client):
    client.force_login(coordinator)
    assert client.get(HOME).status_code == 200


@pytest.mark.django_db
def test_home_renders_for_facilitator(facilitator, client):
    client.force_login(facilitator)
    assert client.get(HOME).status_code == 200


# --- role scoping ---


@pytest.mark.django_db
def test_coordinator_sees_only_own_org_programs(
    coordinator, program, program_two, other_program, client
):
    client.force_login(coordinator)
    content = client.get(HOME).content
    assert b"Tuesday Reading Stars" in content
    assert b"Wednesday Math Club" in content
    assert b"Far Away Program" not in content


@pytest.mark.django_db
def test_facilitator_sees_only_assigned_programs(facilitator, program, program_two, client):
    program.facilitators.add(facilitator)
    client.force_login(facilitator)
    content = client.get(HOME).content
    assert b"Tuesday Reading Stars" in content
    assert b"Wednesday Math Club" not in content


# --- recent activity feed ---


@pytest.mark.django_db
def test_feed_shows_real_attendance_event(coordinator, program, client):
    _log_attendance(program, coordinator, datetime.date.today())
    client.force_login(coordinator)
    content = client.get(HOME).content
    assert b"Logged attendance" in content
    # actor is a staff member the coordinator manages — that is allowed
    assert b"Matthew Ratz" in content


@pytest.mark.django_db
def test_feed_shows_real_publish_event(coordinator, program, client):
    start, end = datetime.date.today().replace(day=1), datetime.date.today()
    publish(build_draft(program, start, end), coordinator)
    client.force_login(coordinator)
    content = client.get(HOME).content
    assert b"Published public profile" in content


@pytest.mark.django_db
def test_feed_fabricates_nothing_when_no_activity(coordinator, program, client):
    client.force_login(coordinator)
    content = client.get(HOME).content.decode()
    assert "No activity logged yet" in content
    assert "No attendance logged yet" in content


# --- PII boundary ---


@pytest.mark.django_db
def test_participant_display_name_does_not_leak(coordinator, program, client):
    _log_attendance(program, coordinator, datetime.date.today(), name=SECRET_NAME)
    client.force_login(coordinator)
    content = client.get(HOME).content.decode()
    assert SECRET_NAME not in content
    # the feed still reports the event, as a program-level count
    assert "1 student" in content


# --- login redirect ---


@pytest.mark.django_db
def test_magic_login_redirects_to_home(coordinator, client):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    response = client.get(f"/auth/magic/{token.token}/")
    assert response.status_code == 302
    assert response.url == HOME


# --- needs-attention (trailing-7-day) logic, unit level ---


@pytest.mark.django_db
def test_program_with_stale_attendance_needs_attention(coordinator, program):
    today = datetime.date(2026, 5, 30)
    _log_attendance(program, coordinator, today - datetime.timedelta(days=10))
    [card] = launchpad.program_cards([program], today=today)
    assert card.needs_attention is True


@pytest.mark.django_db
def test_program_with_recent_attendance_not_flagged(coordinator, program):
    today = datetime.date(2026, 5, 30)
    _log_attendance(program, coordinator, today - datetime.timedelta(days=2))
    [card] = launchpad.program_cards([program], today=today)
    assert card.needs_attention is False
    assert card.last_attendance_date == today - datetime.timedelta(days=2)


@pytest.mark.django_db
def test_program_with_no_attendance_needs_attention(coordinator, program):
    [card] = launchpad.program_cards([program], today=datetime.date(2026, 5, 30))
    assert card.needs_attention is True
    assert card.last_attendance_date is None
