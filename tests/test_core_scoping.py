import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from accounts.models import User
from core.models import Organization, Program, Session
from core.queries import programs_visible_to


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def coordinator_a(org_a):
    return User.objects.create_user(
        email="coord_a@example.com",
        display_name="Coord A",
        organization=org_a,
        role=User.COORDINATOR,
    )


@pytest.fixture
def facilitator_a(org_a):
    return User.objects.create_user(
        email="fac_a@example.com",
        display_name="Fac A",
        organization=org_a,
        role=User.FACILITATOR,
    )


@pytest.fixture
def coordinator_b(org_b):
    return User.objects.create_user(
        email="coord_b@example.com",
        display_name="Coord B",
        organization=org_b,
        role=User.COORDINATOR,
    )


@pytest.fixture
def program_a1(org_a, coordinator_a):
    return Program.objects.create(
        organization=org_a,
        name="Program A1",
        coordinator=coordinator_a,
    )


@pytest.fixture
def program_a2(org_a, coordinator_a):
    return Program.objects.create(
        organization=org_a,
        name="Program A2",
        coordinator=coordinator_a,
    )


@pytest.fixture
def program_b1(org_b, coordinator_b):
    return Program.objects.create(
        organization=org_b,
        name="Program B1",
        coordinator=coordinator_b,
    )


@pytest.mark.django_db
def test_coordinator_sees_all_org_programs(coordinator_a, program_a1, program_a2, program_b1):
    visible = programs_visible_to(coordinator_a)
    assert set(visible) == {program_a1, program_a2}


@pytest.mark.django_db
def test_coordinator_does_not_see_other_org_programs(coordinator_a, program_b1):
    visible = programs_visible_to(coordinator_a)
    assert program_b1 not in visible


@pytest.mark.django_db
def test_facilitator_sees_only_assigned_programs(facilitator_a, program_a1, program_a2, program_b1):
    program_a1.facilitators.add(facilitator_a)
    visible = set(programs_visible_to(facilitator_a))
    assert visible == {program_a1}
    assert program_a2 not in visible
    assert program_b1 not in visible


@pytest.mark.django_db
def test_facilitator_with_no_assignments_sees_nothing(facilitator_a, program_a1):
    visible = programs_visible_to(facilitator_a)
    assert not visible.exists()


@pytest.mark.django_db
def test_program_clean_rejects_cross_org_coordinator(org_a, org_b, coordinator_b):
    program = Program(
        organization=org_a,
        name="Bad Program",
        coordinator=coordinator_b,
    )
    with pytest.raises(ValidationError):
        program.clean()


@pytest.mark.django_db
def test_session_unique_per_program_date(program_a1):
    date = datetime.date(2026, 5, 1)
    Session.objects.create(program=program_a1, scheduled_date=date)
    with pytest.raises(IntegrityError):
        Session.objects.create(program=program_a1, scheduled_date=date)


@pytest.mark.django_db
def test_session_same_date_different_programs_ok(program_a1, program_a2):
    date = datetime.date(2026, 5, 1)
    s1 = Session.objects.create(program=program_a1, scheduled_date=date)
    s2 = Session.objects.create(program=program_a2, scheduled_date=date)
    assert s1.pk != s2.pk
