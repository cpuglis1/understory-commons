# Handoff — Session Guide complete (Slices A–D shipped)

**Date:** 2026-05-31 · **Model:** Opus 4.8 (plan + full build) · **Branch:** `feat/session-guide`
(off `main` @ `cd34601`, pushed). **Suite: 394 passing** (`-m "not live"`).

The session guide is built end to end: **one habit in (set up once → open → attendance →
wrap), two finished outputs out (a reporting card + month-end pay prep)** — and Understory
never moves a dollar. **No LLM in V1** (the AI Slice 2 stays superseded).

## What shipped (commit → slice)
- `2180144` — plan + ADR (STEP 1).
- `e12c8c3` — **Slice A · Setup**: `Program.default_session_length_minutes`/`default_facilitator`;
  `facilitators` M2M → `ProgramFacilitator` through-model (`hourly_rate_cents`, adopted table via
  `SeparateDatabaseAndState`); `Enrollment`; coordinator-only `program_setup` (defaults + per-
  facilitator rate + paste-a-list roster, idempotent + PRG). `programs/<slug>/setup/`.
- `e23926a` — **Slice B · Session guide + Midnight Rule**: `programs/<slug>/log/` (open →
  tap-first attendance with the ghosting Inactive divider + "all here" + "+ Add someone",
  append-only/idempotent commit, present/absent only) → `log/wrap/` (note + Facilitator of
  Record → Save & close commits `closed_at` + default duration). `Session` lifecycle fields;
  `TIME_ZONE → America/New_York`; `close_open_sessions` cron command (`59 23 * * *`),
  idempotent, never fabricates a note. Derived `enrollment_states`/`latest_status_by_participant`.
- `df9305b` — **Slice C · Reporting card**: dashboard per-program card gains the recent trend
  (last 6 sessions present/absent ticks), latest wrap note, and last-logged date + staff actor
  (FoR → recorder fallback) + auto-closed tag. All in `launchpad.program_cards`; no PII.
- `b68d335` — **Slice D · Pay prep**: `attendance/pay.py` (closed sessions × duration × rate per
  FoR, integer cents, flags null-rate/null-FoR — never a silent $0); `FacilitatorPayPeriod`
  (approve/paid state); coordinator-only `/coordinator/pay/` table with month nav, one-field
  reconcile (0 = cancellation), approve, mark-paid, CSV export. Tools menu → "Monthly payroll
  prep" (Beta). Stops at the math.

## Invariants held
PII-light (`display_name` only; no contact/delivery/LLM/photos); `AttendanceRecord` append-only
(corrections append, latest wins); idempotent open + wrap + auto-close; verification chain intact
(donor metrics still only `AttendanceRecord`; pay/notes never enter a snapshot); `programs_visible_to`
scoping (cross-org → 404); no new infra (cron, not a queue).

## To run it live
1. `DJANGO_ENV=dev .venv/bin/python manage.py migrate` (applies core 0005/0006 + attendance 0002/0003;
   the through-model adoption is non-destructive).
2. `manage.py runserver 8000` + `manage.py login_link`, open the magic URL → `/coordinator/`.
3. A program's **Set up program** (rate + roster) → **Open today's session** (tap-first → wrap) →
   dashboard card shows the trend/note → Tools ▾ → **Monthly payroll prep** (approve → export).
   The Midnight Rule: `manage.py close_open_sessions` (wire `59 23 * * *` in prod cron).

## Open / deferred (named, not built)
- **Merge:** branch not yet merged to `main`; `gh` is unauthenticated (PR via web, or `gh auth login`).
- The optional **"on track / behind"** wrap tap was deferred — the free note carries it; add only if
  fieldwork wants it. Backfill (editing a session's date) is today-only in V1.
- Still deferred per plan: photo/testimonial intake, permission forms, satisfaction surveys,
  per-program activity taxonomy, late/excused statuses, per-org timezone, message delivery, real
  payroll (tax/filings/money). All out of V1.
- **Fieldwork:** put it in front of Matthew Ratz (Passion for Learning) — the whole build was shaped
  to his Monday/Sunday-night workflow; validate the roster-paste, default-duration, and FoR-cover edges
  flagged in the plan's "pressure-test" list.
