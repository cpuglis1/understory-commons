"""Session-guide Slice A — program setup (pay defaults + per-facilitator rate + roster).

Coverage from docs/plans/2026-05-31-session-guide.md (Slice A):
- PII probe: roster load stores display_name only — no contact/first/last fields.
- Scoping: coordinator-only; facilitator → 403; cross-org program → 404.
- Paste-a-list creates N Participants + N Enrollments; re-pasting doesn't duplicate.
- Defaults persist: session length, default facilitator, and a per-facilitator
  hourly_rate_cents round-trip; program.facilitators.add() still works (through intact).
"""

import pytest

from accounts.models import User
from attendance.models import Enrollment, Participant
from core.models import Organization, Program, ProgramFacilitator

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
def other_coordinator(other_org):
    return User.objects.create_user(
        email="other@example.com",
        display_name="Other Coord",
        organization=other_org,
        role=User.COORDINATOR,
    )


@pytest.fixture
def program(org, coordinator, facilitator):
    p = Program.objects.create(
        name="Maplewood Film Club", organization=org, coordinator=coordinator
    )
    p.facilitators.add(facilitator)
    return p


@pytest.fixture
def other_program(other_org, other_coordinator):
    return Program.objects.create(
        name="Other Program", organization=other_org, coordinator=other_coordinator
    )


def setup_url(program):
    return f"/coordinator/programs/{program.slug}/setup/"


# --- scoping ---


@pytest.mark.django_db
def test_setup_blocked_for_facilitator(facilitator, program, client):
    client.force_login(facilitator)
    assert client.get(setup_url(program)).status_code == 403


@pytest.mark.django_db
def test_setup_404_for_other_org(coordinator, other_program, client):
    client.force_login(coordinator)
    assert client.get(setup_url(other_program)).status_code == 404


@pytest.mark.django_db
def test_setup_get_renders_rate_field_for_assigned_facilitator(
    coordinator, program, facilitator, client
):
    client.force_login(coordinator)
    response = client.get(setup_url(program))
    assert response.status_code == 200
    # the per-facilitator rate field is named rate_<pk>
    assert f"rate_{facilitator.pk}".encode() in response.content
    assert b"Dana W." in response.content


# --- defaults persist ---


@pytest.mark.django_db
def test_defaults_and_rate_persist(coordinator, program, facilitator, client):
    client.force_login(coordinator)
    response = client.post(
        setup_url(program),
        {
            "default_session_length_minutes": 75,
            "default_facilitator": str(facilitator.pk),
            f"rate_{facilitator.pk}": "35.50",
            "roster": "",
        },
    )
    assert response.status_code == 302  # post-redirect-get

    program.refresh_from_db()
    assert program.default_session_length_minutes == 75
    assert program.default_facilitator_id == facilitator.pk

    link = ProgramFacilitator.objects.get(program=program, facilitator=facilitator)
    assert link.hourly_rate_cents == 3550  # dollars → integer cents, no float drift


@pytest.mark.django_db
def test_blank_rate_leaves_existing_untouched(coordinator, program, facilitator, client):
    # seed a rate, then save the page again with a blank rate field
    ProgramFacilitator.objects.filter(program=program, facilitator=facilitator).update(
        hourly_rate_cents=4000
    )
    client.force_login(coordinator)
    client.post(
        setup_url(program),
        {
            "default_session_length_minutes": 90,
            "default_facilitator": str(facilitator.pk),
            f"rate_{facilitator.pk}": "",  # blank
            "roster": "",
        },
    )
    link = ProgramFacilitator.objects.get(program=program, facilitator=facilitator)
    assert link.hourly_rate_cents == 4000  # blank = leave unchanged, never wiped to null


@pytest.mark.django_db
def test_unassigned_facilitator_cannot_be_default(coordinator, program, org, client):
    outsider = User.objects.create_user(
        email="nope@example.com",
        display_name="Not Assigned",
        organization=org,
        role=User.FACILITATOR,
    )
    client.force_login(coordinator)
    response = client.post(
        setup_url(program),
        {
            "default_session_length_minutes": 90,
            "default_facilitator": str(outsider.pk),  # not assigned to this program
            "roster": "",
        },
    )
    assert response.status_code == 200  # re-renders with a form error, no redirect
    program.refresh_from_db()
    assert program.default_facilitator_id is None


# --- roster load ---


@pytest.mark.django_db
def test_roster_paste_creates_participants_and_enrollments(coordinator, program, org, client):
    client.force_login(coordinator)
    client.post(
        setup_url(program),
        {
            "default_session_length_minutes": 90,
            "roster": "Maria\nJames\nAisha\n",
        },
    )
    names = set(Participant.objects.filter(organization=org).values_list("display_name", flat=True))
    assert names == {"Maria", "James", "Aisha"}
    assert Enrollment.objects.filter(program=program).count() == 3


@pytest.mark.django_db
def test_repaste_does_not_duplicate(coordinator, program, org, client):
    client.force_login(coordinator)
    payload = {"default_session_length_minutes": 90, "roster": "Maria\nJames\n"}
    client.post(setup_url(program), payload)
    client.post(setup_url(program), payload)  # again, plus a dup within one paste below
    client.post(
        setup_url(program),
        {"default_session_length_minutes": 90, "roster": "Maria\nmaria\nMARIA"},
    )
    assert Participant.objects.filter(organization=org, display_name__iexact="maria").count() == 1
    assert Enrollment.objects.filter(program=program).count() == 2  # Maria + James only


@pytest.mark.django_db
def test_existing_org_participant_reused_not_duplicated(coordinator, program, org, client):
    existing = Participant.objects.create(organization=org, display_name="Maria")
    client.force_login(coordinator)
    client.post(
        setup_url(program),
        {"default_session_length_minutes": 90, "roster": "Maria"},
    )
    assert Participant.objects.filter(organization=org, display_name__iexact="maria").count() == 1
    enrollment = Enrollment.objects.get(program=program)
    assert enrollment.participant_id == existing.pk


# --- PII boundary ---


@pytest.mark.django_db
def test_pii_probe_participant_is_display_name_only(coordinator, program, org, client):
    client.force_login(coordinator)
    client.post(
        setup_url(program),
        {"default_session_length_minutes": 90, "roster": "Maria"},
    )
    participant = Participant.objects.get(organization=org, display_name="Maria")
    assert participant.display_name == "Maria"

    # The model must not have grown any identity/contact field across the PII boundary.
    field_names = {f.name for f in Participant._meta.get_fields()}
    forbidden = {"email", "phone", "first_name", "last_name", "contact", "guardian", "dob"}
    assert field_names.isdisjoint(forbidden)


# --- through-model integrity ---


@pytest.mark.django_db
def test_facilitators_add_still_works_through_model(program, org):
    new_fac = User.objects.create_user(
        email="marcus@example.com",
        display_name="Marcus T.",
        organization=org,
        role=User.FACILITATOR,
    )
    program.facilitators.add(new_fac)  # .add() must still work through ProgramFacilitator
    assert program.facilitators.filter(pk=new_fac.pk).exists()
    link = ProgramFacilitator.objects.get(program=program, facilitator=new_fac)
    assert link.hourly_rate_cents is None  # unset rate is null, not a silent $0
