# Handoff — Attendance Coordinator UI (build-sequence step 3)

**Date:** 2026-05-28
**Model:** Opus 4.8
**Branch:** `feat/attendance-coordinator-ui` (not pushed; commit local)
**Scope:** Coordinator-facing web UI for the core attendance loop. No schema
changes, no migrations, no new app. All against existing models.

---

## What shipped

The attendance models, append-only `AttendanceRecord` verification chain, and
admin existed — but there was **no web UI at all** to use them. `attendance/views.py`
was empty, `core/views.py` was only `healthz`, and `magic_login` redirected to `/`,
which 404'd. This session built the Monday-morning loop:

**log in → see your programs → create a session → record who showed up.**

### Files added
- `attendance/queries.py` — read-side reporting. `session_headcount()` and
  `program_month_stats()` are **derived** metrics: computed live from the
  append-only log (latest record per participant wins), never stored. Verification
  chain stays intact.
- `attendance/forms.py` — `SessionForm` (date + notes), `ParticipantForm`
  (`display_name` only — PII boundary held).
- `attendance/views.py` — `dashboard`, `program_detail` (+ session create),
  `session_detail`, `record_attendance`, `participant_create`. All gated by
  `facilitator_or_coordinator_required`; all scoped through
  `core.queries.programs_visible_to` (coordinators see org programs, facilitators
  see only assigned). Cross-org access → 404.
- `attendance/urls.py` — namespace `attendance:`, mounted at root.
- `attendance/templates/attendance/{dashboard,program_detail,session_detail}.html`
- `tests/test_attendance_ui.py` — 16 tests.

### Files changed
- `understory_commons/urls.py` — `path("", include("attendance.urls"))`. `/` is now
  the dashboard, so the magic-link post-login redirect lands somewhere real.
- `templates/base.html` — design tokens + a quiet editorial shell (forest/ink +
  clay accent, serif headings), nav header, Django messages rendering. Replaces the
  bare HTMX-only stub.

---

## Key design decisions (why it's shaped this way)

- **Houses the whole coordinator loop in the existing `attendance` app**, not a new
  `dashboard` app. The architecture doc sketches a `dashboard` app; per CLAUDE.md's
  "no new abstractions / outcome over architecture," one app with one urls.py was the
  lower-ceremony choice. Revisit if a second coordinator surface (grant_finder UI,
  summary) needs a home — that's the second use case that would justify the split.
- **Headcount is derived, never stored.** `attendance/queries.py` recomputes from the
  log every time. This is the donor-surface "verified, re-derivable number" property
  the architecture leans on — wired now even though no donor surface consumes it yet.
- **Append semantics in the write path:** `record_attendance` only writes a new
  `AttendanceRecord` when a participant's status is *new or changed* vs. their latest.
  Re-saving an unchanged form writes nothing; the log stays meaningful.
- **Idempotency** (invariant #4): the attendance form embeds a per-render
  `idempotency_key`. A re-POST with the same key (back/refresh) writes nothing.
- **PII boundary held** (invariant #2): `ParticipantForm` exposes only `display_name`.
  Test `test_participant_form_has_no_pii_fields` locks this.

---

## Verification

- `manage.py check` — clean.
- `pytest tests/test_attendance_ui.py` — **16 passed**.
- Full non-grants suite (ui + coordinator_ui + attendance_flow + core_scoping + auth +
  models) — **70 passed**. (Templates render through the real engine in these tests.)
- Lint: `ruff`/`black` are pre-commit-managed and not installed in `.venv`; run
  `pre-commit run --all-files` before pushing. Code follows existing style.

### To see it live
```
DJANGO_ENV=dev .venv/bin/python manage.py runserver 8001
```
There is no public landing/login page yet — auth is magic-link only. To get a
session: create an org + coordinator (the `accounts` bootstrap path / admin), mint a
magic link, hit `/auth/magic/<token>/`, land on `/`.

---

## Deferred / next candidates (not done, in rough priority)

1. **No coordinator login entry point.** Magic links are minted for *facilitators* by a
   coordinator, and there's a `bootstrap_org` reference in `accounts.models` but no such
   management command found in the tree. A coordinator currently has no self-serve way in.
   Confirm how the first coordinator is created; add a `bootstrap_org` command if missing.
2. **LLM attendance parse.** `AttendanceRecord.source` already has `LLM_PARSE` and the
   model carries `raw_input`/`llm_request_id`, but the UI is manual-form only. The "paste a
   messy sign-in list → parsed count" feature (architecture §5.2) needs the `ai/` provider
   interface, which doesn't exist yet. That's an Opus prompt-design escalation per CLAUDE.md.
3. **Program management UI.** Programs are admin-only to create. Coordinators can't add a
   program from the dashboard yet.
4. **Donor surface / snapshots.** `program_month_stats` produces the derived numbers, but
   `ProfileSnapshot`/`MetricDefinition`/`OutcomeMetric` models and the `discovery` app
   don't exist. That's architecture build-step 4+ and a multi-table schema change (Opus).
5. **Facilitator empty-state polish** and a "this week" view if fieldwork asks.

---

## Note for the next session

CLAUDE.md "Current phase" still says **"Grants ingest — next adapter (TBD)."** This
session worked the *coordinator surface* instead, which is a different lane. Update the
phase block before the next session, and add a dev-log line (done). The grants-ingest
state is unchanged and untouched.
