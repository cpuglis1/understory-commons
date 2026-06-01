# Handoff — Session Guide plan + ADR done; next: Sonnet builds Slice A

**Date:** 2026-05-31 · **Model this session:** Opus 4.8 (planning only — no app code)
**Branch:** `feat/session-guide` (off `main` @ `cd34601`). **Next session = build (Sonnet).**

---

## What shipped this session (STEP 1 — plan)
- **Plan:** `docs/plans/2026-05-31-session-guide.md` — slices A–D, each with a usable deliverable,
  tests, and a re-run fieldwork test (Matthew Ratz). Read this first.
- **ADR:** `docs/decisions/2026-05-31-session-guide-data-model-and-midnight-rule.md` — the schema
  deltas, the M2M→`through` **migration recipe**, the ghosting derivation, the Midnight Rule
  (cron, not a queue), and `TIME_ZONE`→Eastern. Read this for *how* to build the model safely.
- Marked the old AI **Slice 2** in `docs/plans/2026-05-30-coordinator-surface.md` **SUPERSEDED**.
- `CLAUDE.md` "Current phase" updated; `docs/dev-log.md` line appended.

## Three forks confirmed with Chris (don't re-litigate)
1. Facilitator rate = **per (facilitator, program)** → `ProgramFacilitator` through-model.
2. Day boundary = **Eastern** → set `TIME_ZONE = "America/New_York"`.
3. Pay-prep grain = **(facilitator, program, month)** → `FacilitatorPayPeriod`.

## The single most important constraint
**No LLM in this V1.** The brief (`docs/design/2026-05-31-session-guide-concept.md`) wins over the
old Slice 2. Do **not** build `commons/ai/client.py`, a parent-update draft, or an AI parse. New
attendance writes use `source=MANUAL_FORM`; the `LLM_PARSE`/`raw_input`/`llm_request_id` fields stay
dormant (no migration churn).

## Start here (Slice A — Setup)
1. `/clear`, switch to **Sonnet 4.6**, read the plan + ADR.
2. Schema + the M2M→through migration **exactly per ADR D2** (two migrations:
   `SeparateDatabaseAndState` to adopt `core_program_facilitators`, then `AddField hourly_rate_cents`;
   `ProgramFacilitator` is a plain `models.Model`, not `TimestampedModel`). Verify
   `program.facilitators.add()` still works (`accounts/views.py:44`, `test_core_scoping.py:93`,
   `test_coordinator_home.py:237`).
3. Setup form/view (coordinator-only): session length, default facilitator, per-facilitator rate,
   paste-a-list roster → `Participant` + `Enrollment`. Update `seed_attendance` to enroll.
4. Tests per the plan's Slice A list (PII probe, scoping, roster load, defaults persist).
5. Commit per logical unit; push; dev-log line; handoff note. Then Slice B.

## Carry-over code to adapt (not greenfield)
- Append-only/idempotent commit: `feat/attendance-coordinator-ui` @ `da53963`
  (`record_attendance`, `latest_status_by_participant`). uuid→slug; grid→tap-first.
- Read-side/dashboard: `attendance/launchpad.py`, `attendance/views.py::home`/`attendance_log`,
  `templates/base.html` shell + Tools menu, `core/queries.py::programs_visible_to`.

## State / env
- `manage.py check` clean; **342 non-grants tests pass** on `main` going in. `USE_TZ=True`,
  `TIME_ZONE="UTC"` (Slice B flips to Eastern).
- Run it live: `DJANGO_ENV=dev .venv/bin/python manage.py runserver 8000` + `manage.py login_link`.
- `gh` is installed but **unauthenticated** (`gh auth login` for PRs); plain `git push` works.

## Guardrails (unchanged)
PII-light (`display_name` only, no contact, no delivery, no LLM); `AttendanceRecord` append-only;
idempotent open + wrap; verification chain (pay/notes never enter a snapshot); `programs_visible_to`
scoping (cross-org → 404); no new infra without an ADR.
