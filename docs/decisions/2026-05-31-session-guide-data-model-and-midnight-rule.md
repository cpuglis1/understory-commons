# ADR — Session-guide data model + the Midnight Rule auto-close

**Date:** 2026-05-31 · **Status:** Accepted · **Decided with:** Chris (3 forks confirmed below)
**Planning model:** Opus 4.8 · **Implementation:** Sonnet 4.6 (slice by slice)
**Canonical UX:** `docs/design/2026-05-31-session-guide-concept.md` (the brief — source of truth)
**Supersedes:** the AI/LLM portions of `docs/plans/2026-05-30-coordinator-surface.md` §2.5–§2.6
(parent-update draft, coordinator parse, `commons/ai/client.py`). **There is no LLM in this V1.**

This ADR records the schema deltas and the auto-close mechanism. A schema change touching
more than one table is Opus territory (model-routing rules), so the design is settled here
before any Sonnet pass writes migrations.

---

## Context

The brief turns the coordinator surface into a **session guide**: set a program up once, then
each session is two taps (open → attendance, wrap → note), and two admin outputs fall out for
free (a live reporting view; month-end pay prep). The dashboard, the append-only
`AttendanceRecord` log, `programs_visible_to` scoping, and the archived append-only/idempotent
capture loop (`feat/attendance-coordinator-ui` @ `da53963`) already exist. What the brief needs
that the schema does not yet have: program pay defaults, a per-facilitator rate, a per-program
enrolled roster, a session open/closed lifecycle with a duration and a pay-attribution actor,
and an auto-close so an un-wrapped session still counts.

---

## Decisions

### D1 — Facilitator rate lives on a `through` model of the existing `facilitators` M2M
**Confirmed with Chris: per (facilitator, program).**

Rate is a real attribute of *this person facilitating this program*. A single program-level
rate can't pay a senior lead and a junior helper differently in the same program; a single
org-wide per-person rate can't pay the same person more on a harder/longer program. Both are
normal in a tiny CBO. So rate attaches to the assignment.

```python
# core/models.py
class ProgramFacilitator(models.Model):           # NOT TimestampedModel — see migration note
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="facilitator_links")
    facilitator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column="user_id",                       # adopt the existing M2M column
        related_name="program_links",
        limit_choices_to={"role": "facilitator"},
    )
    hourly_rate_cents = models.PositiveIntegerField(null=True, blank=True)  # money as int cents
    class Meta:
        db_table = "core_program_facilitators"     # adopt the existing auto-M2M table
        constraints = [models.UniqueConstraint(fields=["program", "facilitator"],
                                               name="unique_program_facilitator")]

# Program.facilitators becomes:
facilitators = models.ManyToManyField(
    settings.AUTH_USER_MODEL, through="core.ProgramFacilitator",
    related_name="facilitated_programs", limit_choices_to={"role": "facilitator"}, blank=True,
)
```

- **Money as integer cents** (`hourly_rate_cents`), never a float. Display divides by 100.
- `hourly_rate_cents` is **nullable** so existing assignments survive and `program.facilitators.add(user)`
  keeps working (Django allows `.add()` on a `through` M2M when the extra fields are nullable/defaulted).
  A null rate is **not** treated as $0 — pay-prep flags the row "set a rate" (honest, never a silent zero).
- **Blast radius is small:** the only writers are `accounts/views.py:44` (`program.facilitators.add`)
  and tests `test_core_scoping.py:93` / `test_coordinator_home.py:237` — all compatible.

**Why a `through` model is not premature normalization (invariant #5 / "no abstraction without a
2nd use case"):** this is a concrete column on a concrete relationship with a concrete first
consumer (pay-prep), not a base class / plugin / generic adapter. Workflow fit *is* per-person rate.

### D2 — Migration recipe for the M2M→through conversion (preserve existing rows)
Django can't auto-convert a plain M2M to a `through` model without losing the table. Do it in two
migrations so existing assignment rows survive:

1. **`SeparateDatabaseAndState`** — `state_operations` = `[CreateModel(ProgramFacilitator …),
   AlterField(Program.facilitators, through="core.ProgramFacilitator")]`; `database_operations = []`
   (the `core_program_facilitators` table already exists with columns `id, program_id, user_id`;
   `db_column="user_id"` + `db_table` adopt it; the old unique index stays — state-only, no DB op).
2. **`AddField`** — add `hourly_rate_cents` to `ProgramFacilitator` (a real `ALTER TABLE`).

`ProgramFacilitator` is a **plain `models.Model`** (no `TimestampedModel`) on purpose: the adopted
table has no `created_at/updated_at` columns, so inheriting timestamps would desync state from DB.
**Fallback (acceptable — synthetic/dev data only):** if adoption proves fiddly, a clean
recreate of the join table is fine; there is no production data to preserve.

### D3 — Enrollment is a per-program link; `Participant` stays org-scoped
The brief's roster is **per program** (the start-of-year list). `Participant` stays
organization-scoped (one row per kid, `display_name` only, `merged_into` dedupe intact), and a new
link model carries program membership. A kid in two programs is one `Participant` with two
`Enrollment`s — no PII duplication.

```python
# attendance/models.py
class Enrollment(TimestampedModel):
    program = models.ForeignKey("core.Program", on_delete=models.CASCADE, related_name="enrollments")
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="enrollments")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["program", "participant"], name="unique_enrollment")]
```

The in-session roster = the program's enrolled participants. "+ Add someone" creates a
`Participant` (org) **and** an `Enrollment` (program) in one step.

### D4 — ACTIVE/INACTIVE is **derived**, never stored (the ghosting threshold)
No status column on `Enrollment`. Active/inactive is read-side, from the append-only log, so it
self-heals: tapping a ghosting kid present immediately restores them.

**Rule (precise):** for an enrolled participant, take their *latest status per session* across the
program's logged sessions, ordered by `scheduled_date` descending. If the **3 most recent records
that exist for them** are all `absent` → **inactive** (below the divider). Fewer than 3 records, or
any of the last 3 is `present` → **active**. Defined over records that exist (a session with no
record for them is skipped, not assumed absent — we never assert an absence we didn't record).
A new present record breaks the streak on the next read. Lives in `attendance/queries.py` as
`enrollment_states(program) -> (active, inactive)`.

### D5 — Session gains a lifecycle: open → closed, with duration + a pay actor
`Session` is mutable metadata (no append-only guard, unlike `AttendanceRecord`/`ProfileSnapshot`),
so the lifecycle lives here. The `notes` field is reused for the wrap note.

```python
# core/models.py — added to Session
closed_at = models.DateTimeField(null=True, blank=True)          # null => open
facilitator_of_record = models.ForeignKey(                       # PAY source of truth
    settings.AUTH_USER_MODEL, null=True, blank=True,
    on_delete=models.SET_NULL, related_name="sessions_of_record")
duration_minutes = models.PositiveIntegerField(null=True, blank=True)  # committed at close
auto_closed = models.BooleanField(default=False)                 # the "Auto-closed" indicator
# notes: reused for the wrap note ("what did you work on today?")
# @property is_open -> closed_at is None
```

- **`facilitator_of_record` is decoupled from login identity.** `AttendanceRecord.recorded_by`
  (+`recorded_at`) remains the non-repudiable *attendance* attestation (verification chain,
  invariant #1). `facilitator_of_record` is who gets *paid* — so a coordinator can log on a
  facilitator's behalf, and a facilitator covering for another can be credited correctly. It
  defaults to `program.default_facilitator` (or the logged-in facilitator) and is editable on the
  wrap screen.
- **Open vs closed** is `closed_at IS NULL`; "opened" time is just the row's `created_at`
  (no separate `opened_at` — the session is created when opened). Minimal.

### D6 — The Midnight Rule auto-close is a **cron-run management command**, not a queue
**No queue (Django-Q2/RQ/Redis).** A queue is new infra requiring its own ADR and exists to defer
work off a request; this is a once-a-day sweep with no request in flight — a management command on
OS cron is the right size and adds zero infrastructure.

```
# crontab (deploy): 11:59pm Eastern, every day
59 23 * * *  cd /app && python manage.py close_open_sessions
```

`close_open_sessions`:
- Closes every session with `closed_at IS NULL AND scheduled_date <= today_local` (catches up if a
  night was missed). Per close: `closed_at = now`, `duration_minutes = program.default_session_length_minutes`,
  `facilitator_of_record = program.default_facilitator` (may be null → pay-prep flags it),
  `auto_closed = True`.
- **Idempotent:** it only touches `closed_at IS NULL`; a re-run closes nothing already closed.
- **Honest:** it does **not** fabricate a wrap note. `auto_closed=True` drives a visible
  "Auto-closed" tag in the UI (see D7); `notes` stays empty because nothing was logged.

### D7 — "Auto-closed" is a structured boolean, not text injected into `notes`
The brief says auto-close "stamps an 'Auto-closed' system note." Implemented as the `auto_closed`
boolean (D5), surfaced as an "Auto-closed" tag, **not** as free text written into `notes`. Rationale:
`notes` is the facilitator's own content (and what the reporting view reads); a boolean keeps the
indicator queryable (dashboard, pay-prep) and keeps the human note clean. *Deviation flagged for
Chris to veto; recommended as the better engineering choice.*

### D8 — Day boundaries use **Eastern**; set `TIME_ZONE = "America/New_York"`
**Confirmed with Chris.** `USE_TZ=True`, but `TIME_ZONE` was `UTC` while every pilot CBO is DMV/
Eastern. Left as UTC, an 8pm-Eastern session would `get_or_create` onto the *next* calendar day,
and the 11:59pm sweep would fire at ~7pm Eastern — closing live sessions. Setting `TIME_ZONE` to
`America/New_York` makes `timezone.localdate()` ("today") and "11:59pm local" correct everywhere
the day boundary is used. **Per-org timezone is deferred** until a non-Eastern CBO onboards (no
second use case yet — invariant against premature generalization).

### D9 — Pay-prep grain is **(facilitator, program, month)**; a small approval model
**Confirmed with Chris.** Rate (D1) and duration are both per-program, so the payable/approvable
row is per (facilitator_of_record, program, month). For a facilitator who works one program it reads
exactly like the brief's mock. Approve/paid state needs persistence (a status that survives reload):

```python
# attendance/models.py  (built in Slice D)
class FacilitatorPayPeriod(TimestampedModel):
    program = models.ForeignKey("core.Program", on_delete=models.CASCADE, related_name="pay_periods")
    facilitator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pay_periods")
    period_month = models.DateField()              # first-of-month key
    status = models.CharField(max_length=12, choices=[("pending","Pending"),("approved","Approved"),("paid","Paid")], default="pending")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["program","facilitator","period_month"], name="unique_pay_period")]
```

- **Reconcile** ("ran long/short", weather cancellation) = adjusting one session's `duration_minutes`
  (Session is mutable; a cancellation sets it to 0). Pay is **internal**, not a donor-facing verified
  metric, so it is outside the append-only verification chain — a direct edit is acceptable.
- **Understory stops at the math.** No tax, no filings, no money movement; export (CSV) hands the
  approved figures to a bookkeeper / Gusto / QuickBooks. This boundary is what keeps the tool free
  for tiny orgs.

---

## Invariant check

- **#1 Verification chain** — untouched. Donor metrics still derive only from `AttendanceRecord`
  (`recorded_by`/`recorded_at`). `facilitator_of_record`, durations, rates, and notes are
  coordinator-internal and never enter a `ProfileSnapshot`.
- **#2 PII-light** — `Participant` is still `display_name`-only; `Enrollment` adds a program link,
  not a personal field. No contact info, no delivery, no LLM. Names that show on the coordinator
  dashboard (staff actors; the facilitator's own note) are within the coordinator's existing
  workflow and never reach the donor surface.
- **#3 Append-only** — `AttendanceRecord` keeps its `save()` guard; corrections append; reporting
  reads latest-per-(session, participant). Session/Enrollment/pay are mutable *operational* state by
  design, not event-sourced history.
- **#4 Idempotency** — open = `get_or_create(program, scheduled_date)` (existing unique constraint);
  wrap submit carries the per-render `submission_idempotency_key`; the auto-close only touches open rows.
- **#5 Workflow fit** — rate-on-assignment, derived active/inactive, and reuse of `notes` are all
  "matches how the work happens," not schema-elegance. No field the user won't encounter in the flow.

## Schema delta summary (one place)
- **`core.Program`**: `+ default_session_length_minutes` (PositiveInt, default 90), `+ default_facilitator` (FK User, null).
- **`core.ProgramFacilitator`** (new `through`): `+ hourly_rate_cents` (PositiveInt, null). [D1/D2]
- **`core.Session`**: `+ closed_at`, `+ facilitator_of_record`, `+ duration_minutes`, `+ auto_closed`. [D5]
- **`attendance.Enrollment`** (new): `(program, participant)` unique. [D3]
- **`attendance.FacilitatorPayPeriod`** (new, Slice D): approve/paid state. [D9]
- **Settings**: `TIME_ZONE = "America/New_York"`. [D8]
- **Dormant, not removed:** `AttendanceRecord.source=LLM_PARSE`, `raw_input`, `llm_request_id` stay
  in the schema, unwired (no migration churn). New writes use `source=MANUAL_FORM`.
