# Handoff — Coordinator surface: director dashboard (slices 1 + 1.5)

**Date:** 2026-05-31
**Branch:** `feat/donor-surface-step4` (NOT pushed, NOT merged to main)
**Model:** Opus 4.8
**Plan:** `docs/plans/2026-05-30-coordinator-surface.md` (slice 1 + the slice 1.5 addendum)
**Design:** `docs/design/2026-05-30-coordinator-dashboard.md` + approved mockup
`docs/design/mockups/coordinator-dashboard.html`

---

## What shipped

The coordinator home is now a **director dashboard (command center)** — it
replaced the slice-1 "attendance launchpad," which read like an attendance app.

- **App shell** `templates/base.html`: mono-classy top bar (mostly white, black
  text, hairline borders), **Pinyon Script** cursive wordmark, and a **Tools ▾
  mega-menu** over six categories. Honesty rule: only `Live`/`Beta` tools are
  links; `Soon` tools are visible but non-interactive.
- **Dashboard** `attendance:home` (`/coordinator/`): verified org **stat cards**
  (active programs, students reached ✓, sessions held ✓, attendance rate ✓,
  forms-outstanding = honest `—`, profiles live ✓) + a **week/month/all period
  selector** (`?period=`); a **needs-attention** queue (stale attendance + stale
  profile, each deep-linking to the fix); a **programs grid**; a **cross-tool
  activity feed**.
- **Queries** `attendance/launchpad.py`: `resolve_period`, `org_stats`,
  `program_cards`, `recent_activity` — all derived from logged events; no
  participant `display_name` is ever read.
- **Dev command** `manage.py login_link` — mints a fresh magic-link URL.
- Magic-login already redirects to `attendance:home`.

**Tests:** 342 pass — `.venv/bin/python -m pytest -q --ignore=grants_ingest`.
New dashboard coverage in `tests/test_coordinator_home.py` (auth, role scoping,
verified stat counts, honest empties, period windows, needs-attention on/off,
PII probe, Tools-menu Live-link vs Soon-non-link).

**Commits (newest first):** `b6065ad` dev-log · `ea1015a` feat dashboard ·
`2e1d680` docs design+scope · (`84490cb`/`0535589`/`e584dc2` were slice 1).

---

## How to run + see it

```bash
.venv/bin/python manage.py runserver 8000          # start the server
.venv/bin/python manage.py login_link              # prints a fresh login URL — open it
# lands on /coordinator/ as Matthew Ratz; revisit localhost:8000/coordinator/ while the session lasts
```

Dev data (single org): **Passion for Learning** / coordinator **Matthew Ratz**.
Programs: `passion-for-learnin` (seeded attendance + published profile v1) and
`thursday-coding-club` (empty → trips the needs-attention flag).
Reseed: `manage.py seed_attendance --program-slug=<slug>`. **Do not touch
grants_ingest data.**

---

## Invariants honored (re-test if you change the home)

- Verification chain: every ✓ figure derives from `attendance.queries` /
  `launchpad` reads of the log or published `ProfileSnapshot`s. No new source.
- PII-light: dashboard shows counts/rates/statuses + staff actors only — **no
  participant names** (pinned by `test_no_participant_name_leaks`).
- Scoping: all program access via `core.queries.programs_visible_to`.
- Append-only reads; no mutations from the dashboard.

---

## What's next / deferred

- **Slice 2 — attendance-capture screen** (the #1 validated pain). The Tools menu
  "Log attendance" is `Beta` and currently routes to the program list → the
  `attendance:attendance_log` stub (interim: Django admin). Slice 2 builds the
  real manual roster + free-text LLM-parse capture. Needs its own plan section
  before building (prompt design = Opus review).
- Deferred honest stubs: Forms/permissions, timesheets/payroll, family-comm
  drafts, program progress, grant-report sections, find-grants UI, exports — all
  `Soon` in the Tools menu.
- Also deferred: logout + a login landing page (account chip is static now),
  ⌘K search, Reports/Network as top-level pages.

## Gotchas

- Pre-commit `ruff-format` will reformat `.py` and abort the commit; re-`git add`
  and re-commit (the file is already fixed in the working tree).
- A dev server may be left running on `:8000` from the prior session; kill with
  `lsof -ti:8000 | xargs kill -9` before starting a fresh one if needed.
- Memory: `project_coordinator_dashboard_redesign` captures the locked direction.
