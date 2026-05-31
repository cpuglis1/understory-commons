# Handoff — build-step 4: Public Program Page + ProfileSnapshot

**Date:** 2026-05-29
**Branch:** feat/donor-surface-step4 (not yet merged to main)
**Model:** Sonnet 4.6
**Plan:** docs/plans/2026-05-28-step4-public-program-page.md
**ADR:** docs/decisions/2026-05-28-donor-surface-profile-snapshot.md

---

## What shipped

### Slice 0 — `bootstrap_org` management command
`accounts/management/commands/bootstrap_org.py`

Creates the first Organization + coordinator user, mints a magic link, prints
the login URL. Unblocks the live-demo blocker that existed since initial
scaffold. Usage:

```
python manage.py bootstrap_org \
  --org-name="Passion for Learning" \
  --email=matthew@example.com \
  --name="Matthew Ratz"
```

### Slice 1 — Schema
- `core.Organization`: added `slug`, `description`, `location`
- `core.Program`: added `slug`, `summary`
- `core.ProfileSnapshot`: new append-only versioned model (DRAFT / PUBLISHED /
  WITHDRAWN), `save()` guard on PUBLISHED rows, `supersedes` FK, `payload` JSON
- `attendance.queries`: new module with `sessions_held()` and `students_attending()`
  — the only functions allowed to supply numbers to snapshots
- Migration `core/0004_profile_snapshot_slugs_descriptive.py` backfills slugs
  for existing rows

### Slice 2 — Snapshot service
`core/services/snapshots.py`: `build_draft()`, `publish()`, `current_published()`,
`preview_payload()`.

Hard rule: `publish()` re-derives the payload from `attendance.queries` on the
way out — it never trusts the draft's payload. This keeps the verification chain
intact even if someone edited the draft directly.

All six required verification-chain tests pass (see `tests/test_snapshot_service.py`).

### Slice 3 — Public program page
New `discovery` app. Import rule: `core` only, never `attendance` or `accounts`.

`/programs/<slug>/` — 404 if no published snapshot. Unauthenticated. Mobile-first
CSS, provenance badge, donor `base.html`.

### Slice 4 — Coordinator publish flow
`attendance` views (new) under `/coordinator/programs/`:
- `GET /` — program list (facilitator_or_coordinator_required)
- `GET /<slug>/` — program detail: shows last-published state + publish button
- `GET /<slug>/preview/` — renders the donor template against computed-but-unsaved
  payload for the current calendar month
- `POST /<slug>/publish/` — coordinator-only; builds draft + publishes current
  month; supersedes the previous published version

---

## The end-to-end loop (what the demo looks like)

1. `bootstrap_org` → get magic-link login URL
2. Log in as Matthew
3. Create a program via admin (or the attendance app)
4. `GET /coordinator/programs/<slug>/preview/` — see what donors will see
5. `POST /coordinator/programs/<slug>/publish/` — publish current month
6. `GET /programs/<slug>/` — public page, verifiable by any funder with the URL

---

## Open questions resolved this session

- #1 (publish permission): coordinator-only. Facilitators can view the detail
  page but the Publish button requires coordinator role (enforced by decorator).
- #3 (which metrics): sessions_held + students_attending. No others for V1.
- #5 (lean metric layer): MetricDefinition/OutcomeMetric deferred to Compare step.

---

## What's deferred (per plan)

- Discovery feed / browse-all / Compare — step 6
- AI-drafted narrative sections — step 5
- Org-level profile page — its own step
- Background queue for snapshot building (synchronous is fine for current scale)
- Coordinator-side attendance logging UI (currently via admin)
- Coverage window chooser (currently hardcoded to current calendar month)

## Known thin spots

- The coordinator UI (`/coordinator/programs/`) is minimal: list + detail + publish
  only. No attendance-logging UI yet. Coordinators enter attendance via Django admin
  for now.
- `Program.summary`, `Organization.description`, `Organization.location` are editable
  only via Django admin. A coordinator-side edit form is a natural next slice.
- The `base.html` used by coordinator views is the bare HTMX shell. A real
  coordinator shell (nav, auth state) is needed before this is demo-ready beyond
  a technical proof.

## Test count

102 tests pass (excluding grants_ingest). All verification-chain and PII-boundary
tests from the plan's "required before merge" list are green.

## Next session

Before merging, consider:
1. Light coordinator shell template (nav + logged-in state) — 30 min
2. A coordinator-side form for editing `Program.summary` — 30 min
3. Merge to main and run `bootstrap_org` against a local dev DB to verify the
   full loop end to end

Or merge as-is if the goal is just to validate the loop technically, and add
the coordinator-shell work as a separate slice.
