"""Slice 1.5: coordinator home as the director dashboard (command center).

Required-before-merge coverage from docs/plans/2026-05-30-coordinator-surface.md:
- dashboard requires auth; role scoping (coordinator org vs facilitator assigned)
- stat cards reflect real counts; attendance-rate is "—" with no records; Forms
  card is an honest "—"; profiles-live counts published snapshots
- period selector changes the window (week vs month)
- needs-attention surfaces stale attendance + stale profile; empty when none
- no participant display_name appears anywhere on the dashboard
- Tools menu: Live items are links; Soon items are present but not anchors
"""

import datetime

import pytest
from django.utils import timezone

from accounts.models import User
from accounts.services import mint_magic_link
from attendance import launchpad
from attendance.models import AttendanceRecord, Participant
from core.models import Organization, ProfileSnapshot, Program, Session
from core.services.snapshots import build_draft, publish

HOME = "/coordinator/"
FIXED_TODAY = datetime.date(2026, 5, 31)

# Distinctive so a PII leak would be unmistakable in rendered HTML.
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


def _session(program, recorder, on_date, statuses, name=SECRET_NAME):
    """Append one session of real attendance records — the verification-chain event."""
    session = Session.objects.create(program=program, scheduled_date=on_date)
    for i, status in enumerate(statuses):
        participant = Participant.objects.create(
            organization=program.organization, display_name=f"{name} {i}"
        )
        AttendanceRecord.objects.create(
            session=session,
            participant=participant,
            status=status,
            recorded_by=recorder,
            source=AttendanceRecord.MANUAL_FORM,
        )
    return session


def _month(today=FIXED_TODAY):
    return launchpad.resolve_period("month", today=today)


# ======================================================================== #
# Unit: period windows
# ======================================================================== #


def test_resolve_period_defaults_to_month():
    for bad in (None, "", "bogus"):
        assert launchpad.resolve_period(bad, today=FIXED_TODAY).key == "month"


def test_resolve_period_windows():
    week = launchpad.resolve_period("week", today=FIXED_TODAY)
    assert (week.start, week.end) == (datetime.date(2026, 5, 25), FIXED_TODAY)
    month = launchpad.resolve_period("month", today=FIXED_TODAY)
    assert (month.start, month.end) == (datetime.date(2026, 5, 1), FIXED_TODAY)
    assert launchpad.resolve_period("all", today=FIXED_TODAY).start.year == 1900


# ======================================================================== #
# Unit: org stats (verified rollups)
# ======================================================================== #


@pytest.mark.django_db
def test_org_stats_counts_are_verified(coordinator, program, program_two):
    # 3 present + 1 absent this week; one extra session earlier in the month.
    P, A = AttendanceRecord.PRESENT, AttendanceRecord.ABSENT
    _session(program, coordinator, datetime.date(2026, 5, 26), [P, P, P, A])
    _session(program, coordinator, datetime.date(2026, 5, 1), [P])
    stats = launchpad.org_stats([program, program_two], _month())
    assert stats.active_programs == 2
    assert stats.sessions_held == 2
    assert stats.students_reached == 4  # 3 present + 1 present, all distinct
    assert stats.attendance_rate == pytest.approx(4 / 5)  # 4 present of 5 records
    assert stats.profiles_live == 0


@pytest.mark.django_db
def test_org_stats_attendance_rate_none_without_records(coordinator, program):
    stats = launchpad.org_stats([program], _month())
    assert stats.attendance_rate is None
    assert stats.sessions_held == 0


@pytest.mark.django_db
def test_org_stats_profiles_live_counts_published(coordinator, program):
    publish(build_draft(program, datetime.date(2026, 5, 1), FIXED_TODAY), coordinator)
    assert launchpad.org_stats([program], _month()).profiles_live == 1


@pytest.mark.django_db
def test_period_window_changes_counts(coordinator, program):
    _session(program, coordinator, datetime.date(2026, 5, 26), [AttendanceRecord.PRESENT])
    _session(program, coordinator, datetime.date(2026, 5, 1), [AttendanceRecord.PRESENT])
    week = launchpad.resolve_period("week", today=FIXED_TODAY)
    month = launchpad.resolve_period("month", today=FIXED_TODAY)
    assert launchpad.org_stats([program], week).sessions_held == 1
    assert launchpad.org_stats([program], month).sessions_held == 2


# ======================================================================== #
# Unit: program cards + staleness flags
# ======================================================================== #


@pytest.mark.django_db
def test_card_attendance_stale_when_old(coordinator, program):
    _session(
        program, coordinator, FIXED_TODAY - datetime.timedelta(days=10), [AttendanceRecord.PRESENT]
    )
    [card] = launchpad.program_cards([program], _month(), today=FIXED_TODAY)
    assert card.attendance_stale is True


@pytest.mark.django_db
def test_card_not_stale_when_recent(coordinator, program):
    _session(
        program,
        coordinator,
        FIXED_TODAY - datetime.timedelta(days=2),
        [AttendanceRecord.PRESENT, AttendanceRecord.ABSENT],
    )
    [card] = launchpad.program_cards([program], _month(), today=FIXED_TODAY)
    assert card.attendance_stale is False
    assert card.attendance_rate == pytest.approx(0.5)


@pytest.mark.django_db
def test_card_profile_stale_when_old(coordinator, program):
    snap = publish(build_draft(program, datetime.date(2026, 5, 1), FIXED_TODAY), coordinator)
    ProfileSnapshot.objects.filter(pk=snap.pk).update(
        published_at=timezone.now() - datetime.timedelta(days=30)
    )
    [card] = launchpad.program_cards([program], _month(), today=FIXED_TODAY)
    assert card.profile_stale is True


# ======================================================================== #
# View: auth + role scoping
# ======================================================================== #


@pytest.mark.django_db
def test_dashboard_requires_auth(client):
    assert client.get(HOME).status_code == 403


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


# ======================================================================== #
# View: stat cards + honest empties
# ======================================================================== #


@pytest.mark.django_db
def test_dashboard_renders_stat_cards(coordinator, program, client):
    client.force_login(coordinator)
    content = client.get(HOME).content.decode()
    for label in [
        "Active programs",
        "Students reached",
        "Sessions held",
        "Attendance rate",
        "Forms outstanding",
        "Profiles live",
    ]:
        assert label in content


@pytest.mark.django_db
def test_forms_card_is_honest_empty(coordinator, program, client):
    client.force_login(coordinator)
    content = client.get(HOME).content.decode()
    # Forms has no data source yet — the card shows an em dash, not a number.
    assert "Forms outstanding" in content
    assert "—" in content


# ======================================================================== #
# View: period selector
# ======================================================================== #


@pytest.mark.django_db
def test_period_selector_reflects_query(coordinator, program, client):
    client.force_login(coordinator)
    assert b"This month" in client.get(HOME).content  # default
    assert b"This week" in client.get(HOME + "?period=week").content


# ======================================================================== #
# View: needs-attention
# ======================================================================== #


@pytest.mark.django_db
def test_attention_flags_stale_attendance(coordinator, program, client):
    _session(
        program, coordinator, FIXED_TODAY - datetime.timedelta(days=10), [AttendanceRecord.PRESENT]
    )
    client.force_login(coordinator)
    content = client.get(HOME).content.decode()
    assert "Needs attention" in content
    assert "no attendance logged in the last 7 days" in content


@pytest.mark.django_db
def test_attention_flags_stale_profile(coordinator, program, client):
    # recent attendance (so the attendance flag is off), but a stale profile.
    _session(program, coordinator, datetime.date.today(), [AttendanceRecord.PRESENT])
    snap = publish(
        build_draft(program, datetime.date.today().replace(day=1), datetime.date.today()),
        coordinator,
    )
    ProfileSnapshot.objects.filter(pk=snap.pk).update(
        published_at=timezone.now() - datetime.timedelta(days=30)
    )
    client.force_login(coordinator)
    content = client.get(HOME).content.decode()
    assert "public profile is" in content and "stale" in content


@pytest.mark.django_db
def test_no_attention_when_healthy(coordinator, program, client):
    _session(program, coordinator, datetime.date.today(), [AttendanceRecord.PRESENT])
    client.force_login(coordinator)
    assert "Needs attention" not in client.get(HOME).content.decode()


# ======================================================================== #
# View: recent activity + PII boundary
# ======================================================================== #


@pytest.mark.django_db
def test_feed_shows_attendance_and_publish_events(coordinator, program, client):
    _session(program, coordinator, datetime.date.today(), [AttendanceRecord.PRESENT])
    publish(
        build_draft(program, datetime.date.today().replace(day=1), datetime.date.today()),
        coordinator,
    )
    client.force_login(coordinator)
    content = client.get(HOME).content.decode()
    assert "Attendance logged" in content
    assert "Public profile published" in content


@pytest.mark.django_db
def test_no_participant_name_leaks(coordinator, program, client):
    _session(program, coordinator, datetime.date.today(), [AttendanceRecord.PRESENT])
    client.force_login(coordinator)
    content = client.get(HOME).content.decode()
    assert SECRET_NAME not in content


# ======================================================================== #
# View: Tools mega-menu (Live links, Soon non-links)
# ======================================================================== #


@pytest.mark.django_db
def test_tools_menu_live_links_and_soon_non_links(coordinator, client):
    client.force_login(coordinator)
    content = client.get(HOME).content.decode()
    # Live tool is a real link
    assert "/auth/facilitators/new/" in content
    # Soon tool is present but rendered as a non-interactive row
    assert 'class="soon">Roster' in content
    assert "Forms &amp; Permissions" in content


# ======================================================================== #
# Login redirect lands on the dashboard
# ======================================================================== #


@pytest.mark.django_db
def test_magic_login_redirects_to_dashboard(coordinator, client):
    token = mint_magic_link(user=coordinator, created_by=coordinator)
    response = client.get(f"/auth/magic/{token.token}/")
    assert response.status_code == 302
    assert response.url == HOME
