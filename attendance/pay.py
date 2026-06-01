"""Pay-prep aggregation — the month-end byproduct of the session guide (Slice D).

Every figure here is *derived* from closed sessions × the session's committed duration ×
the per-(facilitator, program) rate. Nothing is stored except the approve/paid workflow
state (``FacilitatorPayPeriod``). A row is one (Facilitator of Record, program, month).

Understory stops at the math: it collects hours, does the arithmetic, holds an approval
state, and exports — it does not run payroll (no tax, no filings, no money movement).

Money is integer cents throughout; no float touches an amount.
"""

import calendar
import datetime
from dataclasses import dataclass, field

from core.models import Program, ProgramFacilitator, Session

from .models import FacilitatorPayPeriod


def month_bounds(month_start: datetime.date) -> tuple[datetime.date, datetime.date]:
    """[first, last] dates of the calendar month containing *month_start*."""
    first = month_start.replace(day=1)
    last_day = calendar.monthrange(first.year, first.month)[1]
    return first, first.replace(day=last_day)


def dollars(cents: int | None) -> str | None:
    """Format integer cents as $#,###.## (or None) — no float, no rounding surprises."""
    if cents is None:
        return None
    dollars, rem = divmod(cents, 100)
    return f"${dollars:,}.{rem:02d}"


@dataclass
class PaySession:
    """One closed session in a pay row — surfaced for the one-field reconcile."""

    session: Session
    minutes: int


@dataclass
class PayRow:
    program: Program
    facilitator: object | None  # User, or None for an unassigned (no-FoR) row
    sessions: list[PaySession] = field(default_factory=list)
    minutes: int = 0
    rate_cents: int | None = None
    amount_cents: int | None = None  # None when not computable (no rate / no facilitator)
    status: str = FacilitatorPayPeriod.PENDING
    flag: str | None = None  # "no rate" / "no facilitator" — never silently zeroed

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    @property
    def hours(self) -> float:
        return self.minutes / 60

    @property
    def rate_display(self) -> str | None:
        return dollars(self.rate_cents)

    @property
    def amount_display(self) -> str | None:
        return dollars(self.amount_cents)

    @property
    def payable(self) -> bool:
        """Approvable only when a facilitator and a rate are both known."""
        return self.flag is None


def amount_cents(rate_cents: int, minutes: int) -> int:
    """rate × hours in integer cents, rounded half-up to the nearest cent."""
    return (rate_cents * minutes + 30) // 60


def pay_rows(programs, month_start: datetime.date, month_end: datetime.date) -> list[PayRow]:
    """One row per (Facilitator of Record, program) over the month's **closed** sessions.

    Open sessions are not yet payable and are excluded; the Midnight Rule ensures every
    past day's session is closed with the default duration, so month-end nothing is missed.
    """
    # Approve/paid state for these programs in this month, keyed by (program, facilitator).
    states = {
        (p.program_id, p.facilitator_id): p.status
        for p in FacilitatorPayPeriod.objects.filter(program__in=programs, period_month=month_start)
    }

    rows: list[PayRow] = []
    for program in programs:
        rate_by_facilitator = dict(
            ProgramFacilitator.objects.filter(program=program).values_list(
                "facilitator_id", "hourly_rate_cents"
            )
        )

        closed = (
            Session.objects.filter(
                program=program,
                closed_at__isnull=False,
                scheduled_date__gte=month_start,
                scheduled_date__lte=month_end,
            )
            .select_related("facilitator_of_record")
            .order_by("scheduled_date")
        )

        grouped: dict = {}
        for session in closed:
            grouped.setdefault(session.facilitator_of_record_id, []).append(session)

        for facilitator_id, sessions in grouped.items():
            facilitator = sessions[0].facilitator_of_record  # None for the unassigned row
            minutes = sum(s.duration_minutes or 0 for s in sessions)
            rate_cents = rate_by_facilitator.get(facilitator_id) if facilitator_id else None

            if facilitator_id is None:
                flag, amount = "no facilitator", None
            elif rate_cents is None:
                flag, amount = "no rate", None
            else:
                flag, amount = None, amount_cents(rate_cents, minutes)

            rows.append(
                PayRow(
                    program=program,
                    facilitator=facilitator,
                    sessions=[PaySession(s, s.duration_minutes or 0) for s in sessions],
                    minutes=minutes,
                    rate_cents=rate_cents,
                    amount_cents=amount,
                    status=states.get((program.id, facilitator_id), FacilitatorPayPeriod.PENDING),
                    flag=flag,
                )
            )

    # Stable display order: program name, then facilitator name (unassigned last).
    rows.sort(
        key=lambda r: (
            r.program.name.lower(),
            r.facilitator.display_name.lower() if r.facilitator else "￿",
        )
    )
    return rows


def total_cents(rows: list[PayRow]) -> int:
    """Sum of the computable amounts (flagged rows contribute nothing, not $0 of work)."""
    return sum(r.amount_cents for r in rows if r.amount_cents is not None)
