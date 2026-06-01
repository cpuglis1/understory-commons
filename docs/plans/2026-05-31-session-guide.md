# Plan — Coordinator surface: the Session Guide

**Date:** 2026-05-31 · **Planning model:** Opus 4.8 · **Build model:** Sonnet 4.6 (slice by slice)
**Canonical UX:** `docs/design/2026-05-31-session-guide-concept.md` (the brief — source of truth)
**Data-model + auto-close decisions:** `docs/decisions/2026-05-31-session-guide-data-model-and-midnight-rule.md` (ADR)
**Design tokens:** `docs/design/2026-05-30-coordinator-dashboard.md` (mono-classy; reuse `base.html`)
**Supersedes:** the AI multiplier in `docs/plans/2026-05-30-coordinator-surface.md` §2 (parent-update
draft, coordinator AI-parse, `commons/ai/client.py`). **No LLM in this V1** — the brief wins.

> One habit in (open → attendance → wrap), two finished outputs out (a live reporting view for
> funders/board; month-end pay prep). The facilitator only ever does the middle row.

---

## The fieldwork test (re-run for the whole plan — required before approval)

Matthew Ratz runs Passion for Learning: several programs across DC sites, facilitators paid per
session. **Today:** there is no attendance method, no weekly number, and at month-end he reconstructs
who-ran-what from memory and texts to pay people. **After this build:** at setup he pastes each
program's enrollment list once and sets the session length and each facilitator's rate. Tuesday,
Dana opens *Maplewood Film* on her phone, taps **"all here,"** untaps Marcus, dictates one line
about the final scene, leaves herself as who-ran-it (pre-filled), taps **Save & close** — about two
taps. If she forgets, the **11:59pm Eastern** Midnight Rule closes it with the default 90 minutes so
the day still counts. Sunday, Matthew's dashboard shows Film Club at **86% · "shot the final scene"
· last logged Tue by Dana** — the very line he used to rebuild from memory. Month-end he opens
**pay prep**: Dana 8 sessions × 90 min × $35 = **$420**, pre-computed; he zeroes the one rained-out
Thursday, **approves**, marks **paid**, and **exports** the CSV for his bookkeeper. One habit in,
two finished outputs out, and Understory never moved a dollar. *That paragraph is easy to write, so
the plan is well-shaped.*

---

## Guardrails (do not break — escalate if a slice forces it)
PII-light (`display_name` only; no contact info, no delivery, no photos, **no LLM**); `AttendanceRecord`
append-only (corrections append; reporting reads latest-per-(session, participant)); idempotent open
(`get_or_create`) and wrap (per-render key); verification chain (every donor metric traces to a
`recorded_by`/`recorded_at` record — pay/notes never enter a snapshot); `programs_visible_to(user)`
is the only scoping (cross-org → 404); no new infra without an ADR.

## Carry-over assets (this is adapt-and-extend, not greenfield)
- Append-only/idempotent commit logic: `feat/attendance-coordinator-ui` @ `da53963`
  (`record_attendance` + `latest_status_by_participant`/`session_headcount`). Routing changes
  uuid→slug; screen shape changes grid→tap-first.
- Dashboard read-side: `attendance/launchpad.py` (`program_cards`, `recent_activity`), home view,
  `base.html` shell + Tools mega-menu, the `programs/<slug>/log/` seam (`attendance:attendance_log`).
- Scoping: `core/queries.py::programs_visible_to`. Snapshots: `core/services/snapshots.py`.

---

## Slice A — Setup (coordinator-only): pay defaults + default facilitator + roster load
**Deliverable:** a coordinator configures a program once — session length, the assigned
facilitator(s) with each one's rate, and a pasted roster of first names — and the program now has a
loaded, tappable roster and the two numbers pay-prep needs later.

Scope:
- **Schema (ADR D1/D2/D3/D5-partial):** `Program.default_session_length_minutes` (+90 default),
  `Program.default_facilitator`; convert `facilitators` M2M → `ProgramFacilitator` through
  (`hourly_rate_cents`, null) via the two-migration recipe; `Enrollment` model. *(Session lifecycle
  fields land in Slice B; group migrations sensibly.)*
- **Setup view/form (coordinator-only):** extend program setup with session length, default
  facilitator, per-facilitator rate, and a **paste-a-list** roster box (one first name per line →
  `Participant` + `Enrollment`, dedupe within the org by `display_name` + `merged_into__isnull`).
- **Update `seed_attendance`** to also create `Enrollment`s so seeded programs have a roster.
- Tokens: reuse `base.html`; coordinator-only via `@coordinator_required`.

Tests (`tests/test_session_setup.py`):
- **PII probe:** roster load stores `display_name` only — no contact/first/last fields created.
- **Scoping:** coordinator can only set up programs in their org; facilitator → 403; cross-org → 404.
- Paste-a-list creates N `Participant`s + N `Enrollment`s; re-pasting a name doesn't duplicate.
- Defaults persist: `default_session_length_minutes`, `default_facilitator`, and a per-facilitator
  `hourly_rate_cents` round-trip; `program.facilitators.add()` still works (through-model intact).

## Slice B — The session guide (the heart), on `programs/<slug>/log/`
**Deliverable:** a facilitator runs a real session on a phone — open → tap-first attendance → wrap
note + who-ran-it → Save & close — and the data is captured; an un-wrapped session still counts via
the Midnight Rule.

Scope (upgrades the `attendance:attendance_log` stub into the real screen):
- **Open:** `get_or_create(program, scheduled_date=timezone.localdate())` (idempotent; existing
  unique constraint). Header = program + today.
- **Attendance (tap-first):** chips from `enrollment_states(program)` — active above, the **Inactive
  (ghosting)** divider below (ADR D4), all tappable. **"all here"** sets active present; tap toggles
  **present ↔ absent** (V1 statuses = present/absent only). **"+ Add someone"** → `Participant` +
  `Enrollment` mid-session. Commit is **append-only + idempotent**: write a record only when a
  participant's status is new/changed vs their latest; carry the per-render
  `submission_idempotency_key`; re-POST no-ops. (Adapt `da53963`.) `source=MANUAL_FORM`.
- **Wrap:** free-text **note** → `Session.notes`; **Facilitator of Record** dropdown pre-filled from
  `program.default_facilitator` (or the logged-in facilitator), editable; optional "on track / behind"
  tap *(build the note + FoR first; keep on-track only if it earns its place — §pressure-test)*.
  **Save & close** sets `closed_at`, `duration_minutes = default_session_length_minutes`,
  `facilitator_of_record`.
- **Session lifecycle schema (ADR D5):** `closed_at`, `facilitator_of_record`, `duration_minutes`,
  `auto_closed`.
- **Midnight Rule (ADR D6/D7/D8):** `close_open_sessions` management command (idempotent; closes
  `closed_at IS NULL AND scheduled_date <= today_local`; stamps `auto_closed=True`; commits default
  duration + `default_facilitator`). Set `TIME_ZONE="America/New_York"`. Document the crontab line.
- **Wiring:** Tools menu "Log attendance" stays the entry; dashboard card / program detail gets the
  per-program **Open session** CTA.

Tests (`tests/test_session_guide.py`, `tests/test_midnight_rule.py`):
- Append-only: re-confirming an unchanged roster writes **zero** new records; a correction **appends**
  (latest wins), never mutates (the `save()` guard holds).
- Idempotent **open** (re-open same day = same session) and idempotent **wrap** (re-POST same key = no
  double write / no double close).
- Ghosting derivation: 3-absent-in-a-row → below the Inactive divider; tapping present → active again.
- Facilitator-of-record **overrides** the default and is what pay reads; `recorded_by` stays the
  logged-in user (verification chain intact).
- Scoping: facilitator sees only assigned; cross-org slug → 404.
- present/absent only (late/excused not offered).
- Auto-close: stamps `auto_closed`, commits default duration + default facilitator, and **re-running
  closes nothing already closed**; never fabricates a note.

## Slice C — Reporting (the first free output): richer per-program dashboard card
**Deliverable:** Matthew's dashboard card answers "how's it going" without him rebuilding it — a
recent attendance trend, the latest note, and last-logged + who. He points a board member at it or
exports it.

Scope (extend `attendance/launchpad.py::program_cards` / `ProgramCard`; reuse on the home + program
detail):
- **Recent trend:** last N (≈6) sessions as present/absent ticks (counts only).
- **Latest note:** most recent non-empty `Session.notes`; honest empty when none.
- **Last logged:** date + **staff actor** (`facilitator_of_record.display_name`, falling back to the
  latest record's `recorded_by`). "Auto-closed" sessions render the tag (ADR D7).
- All derived from logged events; no new metric source.

Tests (extend `tests/test_coordinator_home.py`):
- Trend/last-logged reflect real records (constructed sessions yield the expected ticks + date).
- Honest empty state (no sessions → no fabricated trend/note).
- **PII probe:** no participant `display_name` in the trend/last-logged (staff actor + counts only);
  note content (facilitator-authored, coordinator-only) never reaches the donor surface/snapshot.

## Slice D — Pay prep (the second free output): month-end byproduct
**Deliverable:** a coordinator-only monthly pay view — sessions × duration × rate per Facilitator of
Record — with a one-field reconcile, approve, mark-paid, and CSV export. Understory stops at the math.

Scope:
- **Schema (ADR D9):** `FacilitatorPayPeriod` (approve/paid state, `(program, facilitator, month)` unique).
- **Aggregation** (`attendance/pay.py`, new): per (facilitator_of_record, program, month) over
  **closed** sessions — `sessions`, `hours = Σ duration_minutes / 60`, `rate` from
  `ProgramFacilitator.hourly_rate_cents`, `amount` (integer-cents math). Null rate or null FoR → row
  flagged "set a rate" / "assign a facilitator" (never a silent $0).
- **View (coordinator-only):** the month table; **reconcile** = edit one session's `duration_minutes`
  (0 = weather cancellation); **approve** and **mark paid** flip `FacilitatorPayPeriod.status`; **export**
  = CSV of the approved figures. No tax, no filings, no money movement.

Tests (`tests/test_pay_prep.py`):
- hours/amount computed from closed sessions × duration × rate (cents math; no float drift).
- reconcile adjusts exactly one session's contribution; cancellation (0) zeroes that session only.
- approve → paid state persists; CSV export shape (facilitator, program, sessions, hours, rate, amount).
- scoping: coordinator-only; only the coordinator's own org's programs; facilitator → 403.
- null rate / null FoR rows are flagged, not silently zeroed or dropped.

---

## A+B+C+D in one line
A loads the roster and the pay numbers; **B** is the two-tap session a facilitator runs on a phone;
**C** surfaces it to the board/funder for free; **D** is the payroll byproduct for free. Each slice
ends with a thing a real CBO coordinator or funder could use on Monday.

## To pressure-test during build (from the brief)
- Roster: paste-a-list vs add-one-at-a-time — confirm paste matches how the enrollment list exists.
- Default duration: is "set once per program" true enough, or is the monthly adjust used often?
- The "on track / behind" tap: does it earn its place, or is the free note enough? (Default: ship the
  note; add on-track only if it pulls weight.)
- Who-ran-it edge: a facilitator covering for another — does "whoever the FoR dropdown says" hold?

## Explicitly NOT in this build (named so they aren't improvised in)
LLM anything (parent-draft, parse, `commons/ai/client.py`); message delivery; photo/testimonial
intake; permission/release tracking; satisfaction surveys; per-program custom activity taxonomy;
late/excused statuses; structured participant names; per-org timezone; donor-surface/snapshot changes;
background queue; actual payroll (tax/filing/money movement). All deferred, none built here.

## Phase discipline
Commit per logical unit; push; one dev-log line per session; end each session with a
`docs/handoffs/` note. Plan-then-build: this doc + the ADR are STEP 1 (Opus); STEP 2 is Sonnet,
slice by slice. If a slice reveals the plan is wrong, stop and update this doc — don't paper over it.
