"""Session-guide Slice D — pay prep (the month-end byproduct).

Coverage from docs/plans/2026-05-31-session-guide.md (Slice D):
- hours/amount computed from closed sessions × duration × rate (integer cents, no float)
- only closed sessions are payable; reconcile adjusts a single session (0 = cancellation)
- approve → paid state persists; CSV export shape
- scoping: coordinator-only; cross-org adjust → 404
- null rate / null Facilitator-of-Record rows are flagged, never silently zeroed/dropped
"""

import datetime

import pytest
from django.utils import timezone

from accounts.models import User
from attendance import pay
from attendance.models import FacilitatorPayPeriod
from core.models import Organization, Program, ProgramFacilitator, Session

MONTH_START = datetime.date(2026, 5, 1)
MONTH_END = datetime.date(2026, 5, 31)
MONTH_PARAM = "2026-05"
PAY_URL = "/coordinator/pay/"


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
    ProgramFacilitator.objects.filter(program=p, facilitator=facilitator).update(
        hourly_rate_cents=3500  # Dana $35/hr; Marcus intentionally has no rate
    )
    return p


@pytest.fixture
def other_program(other_org, other_coordinator):
    return Program.objects.create(
        name="Other Program", organization=other_org, coordinator=other_coordinator
    )


def closed_session(program, day, facilitator, minutes=90):
    return Session.objects.create(
        program=program,
        scheduled_date=datetime.date(2026, 5, day),
        closed_at=timezone.now(),
        duration_minutes=minutes,
        facilitator_of_record=facilitator,
    )


def _rows(program):
    return pay.pay_rows([program], MONTH_START, MONTH_END)


# --- the math (unit) ---


def test_amount_cents_rounds_half_up():
    assert pay.amount_cents(3500, 90) == 5250  # $35 × 1.5h = $52.50
    assert pay.amount_cents(3550, 90) == 5325  # $35.50 × 1.5h = $53.25
    assert pay.amount_cents(3333, 90) == 5000  # 4999.5 → 5000 (no float drift)


@pytest.mark.django_db
def test_pay_row_hours_and_amount(program, facilitator):
    for day in range(1, 9):  # 8 closed sessions × 90 min
        closed_session(program, day, facilitator, 90)
    [row] = [r for r in _rows(program) if r.facilitator == facilitator]
    assert row.session_count == 8
    assert row.minutes == 720
    assert row.hours == 12.0
    assert row.rate_cents == 3500
    assert row.amount_cents == 42000
    assert row.amount_display == "$420.00"  # matches the brief's mock


@pytest.mark.django_db
def test_only_closed_sessions_are_payable(program, facilitator):
    closed_session(program, 5, facilitator, 90)
    Session.objects.create(  # open (not wrapped) → not payable
        program=program,
        scheduled_date=datetime.date(2026, 5, 6),
        duration_minutes=90,
        facilitator_of_record=facilitator,
    )
    [row] = [r for r in _rows(program) if r.facilitator == facilitator]
    assert row.session_count == 1


# --- flags: never a silent $0 ---


@pytest.mark.django_db
def test_null_rate_is_flagged_not_zeroed(program, facilitator2):
    closed_session(program, 5, facilitator2, 90)  # Marcus has no rate
    [row] = [r for r in _rows(program) if r.facilitator == facilitator2]
    assert row.flag == "no rate"
    assert row.amount_cents is None
    assert row.payable is False


@pytest.mark.django_db
def test_null_facilitator_is_flagged(program):
    Session.objects.create(
        program=program,
        scheduled_date=datetime.date(2026, 5, 5),
        closed_at=timezone.now(),
        duration_minutes=90,
        facilitator_of_record=None,
    )
    [row] = [r for r in _rows(program) if r.facilitator is None]
    assert row.flag == "no facilitator"
    assert row.amount_cents is None


@pytest.mark.django_db
def test_total_excludes_flagged_rows(program, facilitator):
    closed_session(program, 5, facilitator, 90)  # payable: $52.50
    Session.objects.create(  # flagged (no FoR) — not counted
        program=program,
        scheduled_date=datetime.date(2026, 5, 6),
        closed_at=timezone.now(),
        duration_minutes=90,
        facilitator_of_record=None,
    )
    assert pay.total_cents(_rows(program)) == 5250


# --- reconcile (view) ---


@pytest.mark.django_db
def test_reconcile_adjusts_one_session(program, facilitator, coordinator, client):
    s1 = closed_session(program, 5, facilitator, 90)
    s2 = closed_session(program, 6, facilitator, 90)
    client.force_login(coordinator)
    client.post(
        "/coordinator/pay/adjust/",
        {"session_id": str(s1.id), "duration_minutes": "45", "month": MONTH_PARAM},
    )
    s1.refresh_from_db()
    s2.refresh_from_db()
    assert s1.duration_minutes == 45  # adjusted
    assert s2.duration_minutes == 90  # untouched


@pytest.mark.django_db
def test_reconcile_cancellation_zeroes_one_session(program, facilitator, coordinator, client):
    s1 = closed_session(program, 5, facilitator, 90)
    client.force_login(coordinator)
    client.post(
        "/coordinator/pay/adjust/",
        {"session_id": str(s1.id), "duration_minutes": "0", "month": MONTH_PARAM},
    )
    s1.refresh_from_db()
    assert s1.duration_minutes == 0  # weather cancellation → $0 for that session


# --- approve → paid (view) ---


@pytest.mark.django_db
def test_approve_then_paid_persists(program, facilitator, coordinator, client):
    closed_session(program, 5, facilitator, 90)
    client.force_login(coordinator)
    base = {
        "program_id": str(program.id),
        "facilitator_id": str(facilitator.id),
        "month": MONTH_PARAM,
    }

    client.post("/coordinator/pay/approve/", base)
    period = FacilitatorPayPeriod.objects.get(
        program=program, facilitator=facilitator, period_month=MONTH_START
    )
    assert period.status == FacilitatorPayPeriod.APPROVED
    assert period.approved_by_id == coordinator.pk
    assert period.approved_at is not None

    client.post("/coordinator/pay/paid/", base)
    period.refresh_from_db()
    assert period.status == FacilitatorPayPeriod.PAID
    assert period.paid_at is not None


# --- CSV export (view) ---


@pytest.mark.django_db
def test_csv_export_shape(program, facilitator, coordinator, client):
    closed_session(program, 5, facilitator, 90)  # one 90-min session → $52.50
    client.force_login(coordinator)
    response = client.get(PAY_URL, {"month": MONTH_PARAM, "export": "csv"})
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    body = response.content.decode()
    assert "Facilitator,Program,Sessions,Hours,Rate,Amount,Status" in body
    assert "Dana W." in body
    assert "Maplewood Film Club" in body
    assert "$52.50" in body


@pytest.mark.django_db
def test_pay_page_renders_amount(program, facilitator, coordinator, client):
    closed_session(program, 5, facilitator, 90)
    client.force_login(coordinator)
    response = client.get(PAY_URL, {"month": MONTH_PARAM})
    assert response.status_code == 200
    assert b"$52.50" in response.content
    assert b"Approve" in response.content


# --- scoping ---


@pytest.mark.django_db
def test_facilitator_cannot_access_pay(facilitator, client):
    client.force_login(facilitator)
    assert client.get(PAY_URL).status_code == 403


@pytest.mark.django_db
def test_cross_org_adjust_404(coordinator, other_program, client):
    s = Session.objects.create(
        program=other_program,
        scheduled_date=datetime.date(2026, 5, 5),
        closed_at=timezone.now(),
        duration_minutes=90,
    )
    client.force_login(coordinator)
    response = client.post(
        "/coordinator/pay/adjust/",
        {"session_id": str(s.id), "duration_minutes": "30", "month": MONTH_PARAM},
    )
    assert response.status_code == 404
    s.refresh_from_db()
    assert s.duration_minutes == 90  # cross-org session untouched
