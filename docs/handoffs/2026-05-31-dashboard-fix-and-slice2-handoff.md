# Handoff — dashboard merge-fix done; next: plan slice 2 (attendance tracker)

**Date:** 2026-05-31
**Branch/state:** `main` @ `3c73d64`, **pushed to origin** (origin/main matches).
**Model this session:** Opus 4.8 (fix only). **Next session = planning (Opus).**

---

## What just happened (context, not work to redo)

`origin/main` was **broken**. The earlier `d670037` merge ("Merge branch 'main'
into feat/donor-surface-step4") resolved an attendance conflict by taking the
**step-3 attendance-loop** branch wholesale and dropping the **slice-1.5 dashboard**
wiring: magic-login `NoReverseMatch: attendance:home`, `attendance.queries` missing
`sessions_held`/`students_attending` (snapshot service + launchpad + dashboard all
down), discovery mount dropped. The suite couldn't even collect.

**Fixed** by restoring the known-good dashboard tip `ef89660`
(`attendance/{views,urls,queries,forms}.py`, `program_detail.html`,
`templates/base.html`, root `urls.py`) and removing the step-3 orphans. Now:
`manage.py check` clean, **342 non-grants tests pass**, live login → `/coordinator/`
renders the dashboard. Done; don't revisit unless something regresses.

---

## Next phase: plan slice 2 — attendance capture (the #1 validated pain)

This is a **planning session** → output a plan doc, then `/clear` + Sonnet to build.
Per CLAUDE.md: AI free-text parse prompt design is an **Opus escalation** (the prompt
is the contract — design it in the plan before any LLM calls scale).

### The single most important asset
The manual attendance-capture loop was **already built** in step 3 and is **archived**,
not lost, on branch **`feat/attendance-coordinator-ui`** (commit **`da53963`**). Its
handoff is still in the tree: `docs/handoffs/2026-05-28-attendance-coordinator-ui.md`
(read it first). That branch has:
- `session_detail` roster check-off view + template
- `record_attendance` — **append-only, idempotent** writes (only writes on new/changed
  status; per-render `idempotency_key`; honors invariants #3 and #4)
- `participant_create` (PII boundary held — `display_name` only)
- `attendance/queries.py` `session_headcount` / `program_month_stats` (derived, not stored)
- `tests/test_attendance_ui.py` (16 tests)

Slice 2 is **largely "reconcile + adapt that code onto the dashboard," then add LLM parse** —
not greenfield.

### The reconciliation the plan must resolve
The two surfaces route differently:
- **Dashboard (on main now):** slug-based — `attendance:program_detail` (`<slug>`),
  and a **stub seam** `attendance:attendance_log` (`programs/<slug>/log/`,
  `attendance/views.py::attendance_log`). Tools-menu "Log attendance" is **Beta** and
  points here. This stub is where the real capture screen lands.
- **Step-3 (archived):** uuid-based `program_detail` (`<uuid:pk>`) + `session_detail`
  by session pk + `record_attendance`.

Plan needs to decide: keep slug program routing (yes — it's the merged convention),
slot the session→roster→record flow under the `attendance_log` seam, and pick the
session-selection UX (today's session, create if absent, idempotent).

### Model support already present (no schema change expected)
`AttendanceRecord` already carries `source` (`MANUAL_FORM`, **`LLM_PARSE`**),
`raw_input`, `llm_request_id`, `submission_idempotency_key`. So manual + parse paths
both have a home in the existing schema. **The `ai/` provider interface does NOT exist
yet** — the LLM parse needs it; that's part of slice-2 scope/plan.

### Plan against
`docs/plans/2026-05-30-coordinator-surface.md` — the **Slice 2** section (lines ~84–96)
is a sketch only ("do not build from this — it gets its own plan section"). This next
session writes that section. Re-run the **fieldwork test** (Matthew Ratz / Passion for
Learning) before approving.

### Guardrails (unchanged)
Verification chain (every donor-facing number traces to a logged event), PII-light
(`display_name` only, no contact info, no delivery), append-only event log,
idempotent inbound, `programs_visible_to` scoping.

---

## Loose ends (not blocking slice 2)
- **CLAUDE.md "Current phase"** still says *"Grants ingest — next adapter."* Stale since
  the coordinator surface took over. Update it at the top of the next session.
- `gh` is installed but **unauthenticated** (`gh auth login` needed for any PR work);
  plain `git push` works via macOS keychain.
- Untracked working-dir cruft (`.claude/`, `agentic_grant_tool/`, `exports/`,
  `profiles/all.yaml`, `results.csv`, `understory_architecture.md`) — not part of the
  fix, left alone.
- To see it live: `DJANGO_ENV=dev .venv/bin/python manage.py runserver 8000` +
  `manage.py login_link`, open the magic URL → `/coordinator/`.
