"""Session-guide Slice B — the Midnight Rule auto-close (session-guide ADR D6/D7).

- closes an open past-dated session: stamps closed_at, commits the program's default
  duration + default facilitator, marks auto_closed, leaves the note empty (no fabrication)
- idempotent: a second run closes nothing already closed
- leaves future-dated and already-closed sessions alone
- a null default facilitator still closes (FoR null → pay-prep flags it)
"""

import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.models import User
from core.models import Organization, Program, Session


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Passion for Learning")


@pytest.fixture
def coordinator(org):
    return User.objects.create_user(
        email="coord@example.com",
        display_name="Matthew Ratz",
        organization=org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def facilitator(org):
    return User.objects.create_user(
        email="dana@example.com",
        display_name="Dana W.",
        organization=org,
        role=User.FACILITATOR,
    )


@pytest.fixture
def program(org, coordinator, facilitator):
    p = Program.objects.create(
        name="Maplewood Film Club",
        organization=org,
        coordinator=coordinator,
        default_session_length_minutes=90,
        default_facilitator=facilitator,
    )
    p.facilitators.add(facilitator)
    return p


def _yesterday():
    return timezone.localdate() - datetime.timedelta(days=1)


@pytest.mark.django_db
def test_autoclose_closes_open_past_session(program, facilitator):
    session = Session.objects.create(program=program, scheduled_date=_yesterday())
    call_command("close_open_sessions")
    session.refresh_from_db()
    assert session.closed_at is not None
    assert session.duration_minutes == 90  # the program default
    assert session.facilitator_of_record_id == facilitator.pk
    assert session.auto_closed is True
    assert session.notes == ""  # never fabricates a wrap note


@pytest.mark.django_db
def test_autoclose_is_idempotent(program):
    session = Session.objects.create(program=program, scheduled_date=_yesterday())
    call_command("close_open_sessions")
    session.refresh_from_db()
    first_closed_at = session.closed_at

    call_command("close_open_sessions")  # re-run
    session.refresh_from_db()
    assert session.closed_at == first_closed_at  # nothing re-closed


@pytest.mark.django_db
def test_autoclose_skips_future_session(program):
    tomorrow = timezone.localdate() + datetime.timedelta(days=1)
    session = Session.objects.create(program=program, scheduled_date=tomorrow)
    call_command("close_open_sessions")
    session.refresh_from_db()
    assert session.closed_at is None  # future day left open


@pytest.mark.django_db
def test_autoclose_leaves_already_closed_session(program):
    closed_at = timezone.now() - datetime.timedelta(hours=2)
    session = Session.objects.create(
        program=program,
        scheduled_date=_yesterday(),
        closed_at=closed_at,
        duration_minutes=120,
        auto_closed=False,
    )
    call_command("close_open_sessions")
    session.refresh_from_db()
    assert session.closed_at == closed_at  # untouched
    assert session.duration_minutes == 120
    assert session.auto_closed is False  # a human-closed session stays human-closed


@pytest.mark.django_db
def test_autoclose_with_null_default_facilitator(org, coordinator):
    program = Program.objects.create(
        name="No Default",
        organization=org,
        coordinator=coordinator,
        default_session_length_minutes=60,
        default_facilitator=None,
    )
    session = Session.objects.create(program=program, scheduled_date=_yesterday())
    call_command("close_open_sessions")
    session.refresh_from_db()
    assert session.closed_at is not None
    assert session.duration_minutes == 60
    assert session.facilitator_of_record_id is None  # flagged by pay-prep, not blocked
    assert session.auto_closed is True
