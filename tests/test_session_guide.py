"""Session-guide Slice B — the in-session guide (open → attendance → wrap).

Coverage from docs/plans/2026-05-31-session-guide.md (Slice B):
- idempotent open (re-open same day = one session) + idempotent wrap (no double close)
- append-only commit: unchanged status writes nothing; correction appends (latest wins)
- present/absent only
- ghosting derivation: 3 absent in a row → inactive; reappear → active
- Facilitator of Record overrides the default; recorded_by stays the logged-in user
- "+ Add someone" enrolls a display_name-only participant
- scoping: facilitator sees only assigned; cross-org → 404; unauth → 403
"""

import datetime

import pytest

from accounts.models import User
from attendance.models import AttendanceRecord, Enrollment, Participant
from attendance.queries import enrollment_states, latest_status_by_participant
from core.models import Organization, Program, Session

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
def facilitator(org):
    return User.objects.create_user(
        email="dana@example.com",
        display_name="Dana W.",
        organization=org,
        role=User.FACILITATOR,
    )


@pytest.fixture
def facilitator2(org):
    return User.objects.create_user(
        email="marcus@example.com",
        display_name="Marcus T.",
        organization=org,
        role=User.FACILITATOR,
    )


@pytest.fixture
def unassigned_facilitator(org):
    return User.objects.create_user(
        email="nope@example.com",
        display_name="Unassigned",
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
def program(org, coordinator, facilitator, facilitator2):
    p = Program.objects.create(
        name="Maplewood Film Club",
        organization=org,
        coordinator=coordinator,
        default_session_length_minutes=90,
        default_facilitator=facilitator,
    )
    p.facilitators.add(facilitator)
    p.facilitators.add(facilitator2)
    return p


@pytest.fixture
def other_program(other_org, other_coordinator):
    return Program.objects.create(
        name="Other Program", organization=other_org, coordinator=other_coordinator
    )


@pytest.fixture
def roster(org, program):
    people = {}
    for name in ("Maria", "James", "Aisha"):
        p = Participant.objects.create(organization=org, display_name=name)
        Enrollment.objects.create(program=program, participant=p)
        people[name] = p
    return people


def log_url(program):
    return f"/coordinator/programs/{program.slug}/log/"


def add_url(program):
    return f"/coordinator/programs/{program.slug}/log/add/"


def wrap_url(program):
    return f"/coordinator/programs/{program.slug}/log/wrap/"


def _record(session, participant, status, by):
    return AttendanceRecord.objects.create(
        session=session,
        participant=participant,
        status=status,
        recorded_by=by,
        source=AttendanceRecord.MANUAL_FORM,
    )


# --- open / render ---


@pytest.mark.django_db
def test_open_is_idempotent(facilitator, program, roster, client):
    client.force_login(facilitator)
    client.get(log_url(program))
    client.get(log_url(program))
    assert Session.objects.filter(program=program).count() == 1


@pytest.mark.django_db
def test_guide_get_renders_roster(facilitator, program, roster, client):
    client.force_login(facilitator)
    response = client.get(log_url(program))
    assert response.status_code == 200
    assert b"Maria" in response.content
    assert b"all here" in response.content


@pytest.mark.django_db
def test_wrap_get_renders(facilitator, program, roster, client):
    client.force_login(facilitator)
    response = client.get(wrap_url(program))
    assert response.status_code == 200
    assert b"How'd today go?" in response.content


# --- commit / append-only / idempotency ---


def _present_post(roster, key="k1"):
    data = {"idempotency_key": key}
    for p in roster.values():
        data[f"status_{p.id}"] = "present"
    return data


@pytest.mark.django_db
def test_commit_appends_records_and_advances_to_wrap(facilitator, program, roster, client):
    client.force_login(facilitator)
    response = client.post(log_url(program), _present_post(roster))
    assert response.status_code == 302
    assert response.url == wrap_url(program)
    records = AttendanceRecord.objects.filter(session__program=program)
    assert records.count() == 3
    rec = records.first()
    assert rec.recorded_by_id == facilitator.pk  # attestation = logged-in user
    assert rec.source == AttendanceRecord.MANUAL_FORM


@pytest.mark.django_db
def test_unchanged_status_writes_nothing(facilitator, program, roster, client):
    client.force_login(facilitator)
    client.post(log_url(program), _present_post(roster, key="k1"))
    # same statuses, fresh key → falls through to changed-only logic, writes nothing
    client.post(log_url(program), _present_post(roster, key="k2"))
    assert AttendanceRecord.objects.filter(session__program=program).count() == 3


@pytest.mark.django_db
def test_repost_same_key_is_idempotent(facilitator, program, roster, client):
    client.force_login(facilitator)
    client.post(log_url(program), _present_post(roster, key="k1"))
    # same key, even with different statuses → short-circuits, writes nothing
    data = {"idempotency_key": "k1"}
    for p in roster.values():
        data[f"status_{p.id}"] = "absent"
    client.post(log_url(program), data)
    assert AttendanceRecord.objects.filter(session__program=program).count() == 3


@pytest.mark.django_db
def test_correction_appends_not_mutates(facilitator, program, roster, client):
    client.force_login(facilitator)
    maria = roster["Maria"]
    client.post(log_url(program), {"idempotency_key": "k1", f"status_{maria.id}": "present"})
    client.post(log_url(program), {"idempotency_key": "k2", f"status_{maria.id}": "absent"})
    maria_records = AttendanceRecord.objects.filter(participant=maria)
    assert maria_records.count() == 2  # appended, not mutated
    session = Session.objects.get(program=program)
    assert latest_status_by_participant(session)[maria.id] == "absent"  # latest wins


@pytest.mark.django_db
def test_present_absent_only(facilitator, program, roster, client):
    client.force_login(facilitator)
    maria = roster["Maria"]
    client.post(log_url(program), {"idempotency_key": "k1", f"status_{maria.id}": "late"})
    assert AttendanceRecord.objects.filter(participant=maria).count() == 0  # late not offered


# --- + Add someone ---


@pytest.mark.django_db
def test_add_someone_enrolls_display_name_only(facilitator, program, org, roster, client):
    client.force_login(facilitator)
    response = client.post(add_url(program), {"display_name": "Devon"})
    assert response.status_code == 302
    devon = Participant.objects.get(organization=org, display_name="Devon")
    assert Enrollment.objects.filter(program=program, participant=devon).exists()
    field_names = {f.name for f in Participant._meta.get_fields()}
    assert field_names.isdisjoint({"email", "phone", "first_name", "last_name"})


# --- ghosting derivation ---


@pytest.mark.django_db
def test_ghosting_marks_inactive_then_reactivates(facilitator, program, roster):
    maria, james = roster["Maria"], roster["James"]
    today = datetime.date.today()
    # three logged sessions: Maria absent each time, James present each time
    for i in range(3):
        s = Session.objects.create(
            program=program, scheduled_date=today - datetime.timedelta(days=3 - i)
        )
        _record(s, maria, AttendanceRecord.ABSENT, facilitator)
        _record(s, james, AttendanceRecord.PRESENT, facilitator)

    active, inactive = enrollment_states(program)
    assert maria in inactive
    assert james in active

    # Maria reappears (a later present record) → active again on next read
    s4 = Session.objects.create(program=program, scheduled_date=today)
    _record(s4, maria, AttendanceRecord.PRESENT, facilitator)
    active, inactive = enrollment_states(program)
    assert maria in active
    assert maria not in inactive


@pytest.mark.django_db
def test_guide_renders_inactive_divider(facilitator, program, roster, client):
    maria = roster["Maria"]
    today = datetime.date.today()
    for i in range(3):
        s = Session.objects.create(
            program=program, scheduled_date=today - datetime.timedelta(days=10 - i)
        )
        _record(s, maria, AttendanceRecord.ABSENT, facilitator)
    client.force_login(facilitator)
    response = client.get(log_url(program))
    assert response.status_code == 200
    assert b"Inactive" in response.content


# --- wrap ---


@pytest.mark.django_db
def test_wrap_close_sets_duration_for_and_note(facilitator, program, roster, client):
    client.force_login(facilitator)
    response = client.post(
        wrap_url(program),
        {"note": "shot the final scene", "facilitator_of_record": str(facilitator.pk)},
    )
    assert response.status_code == 302
    assert response.url == "/coordinator/"
    session = Session.objects.get(program=program)
    assert session.closed_at is not None
    assert session.duration_minutes == 90  # the program default
    assert session.facilitator_of_record_id == facilitator.pk
    assert session.notes == "shot the final scene"
    assert session.auto_closed is False  # a human wrap, not the Midnight Rule


@pytest.mark.django_db
def test_for_overrides_default_and_is_decoupled_from_login(
    facilitator, facilitator2, program, roster, client
):
    # logged in as facilitator (default FoR), but credit facilitator2 who covered
    client.force_login(facilitator)
    client.post(log_url(program), _present_post(roster))  # records recorded_by=facilitator
    client.post(
        wrap_url(program),
        {"note": "", "facilitator_of_record": str(facilitator2.pk)},
    )
    session = Session.objects.get(program=program)
    assert session.facilitator_of_record_id == facilitator2.pk  # pay attribution overridden
    # attestation is still the logged-in user, decoupled from pay
    assert AttendanceRecord.objects.filter(session=session, recorded_by=facilitator).exists()


@pytest.mark.django_db
def test_wrap_is_idempotent_no_double_close(facilitator, program, roster, client):
    client.force_login(facilitator)
    client.post(wrap_url(program), {"note": "first", "facilitator_of_record": str(facilitator.pk)})
    session = Session.objects.get(program=program)
    first_closed_at = session.closed_at

    client.post(wrap_url(program), {"note": "second", "facilitator_of_record": str(facilitator.pk)})
    session.refresh_from_db()
    assert session.closed_at == first_closed_at  # not re-closed
    assert session.duration_minutes == 90


# --- scoping ---


@pytest.mark.django_db
def test_unassigned_facilitator_404(unassigned_facilitator, program, roster, client):
    client.force_login(unassigned_facilitator)
    assert client.get(log_url(program)).status_code == 404


@pytest.mark.django_db
def test_cross_org_404(coordinator, other_program, client):
    client.force_login(coordinator)
    assert client.get(log_url(other_program)).status_code == 404


@pytest.mark.django_db
def test_unauthenticated_forbidden(program, client):
    assert client.get(log_url(program)).status_code == 403
