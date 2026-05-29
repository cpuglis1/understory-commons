# Plan — Public Program Page + ProfileSnapshot (build-sequence step 4)

**Date:** 2026-05-28
**Planning model:** Opus 4.7
**Implements:** `understory_architecture.md` §8 step 4 — "Snapshot service + a
single public program page. Now the loop is visible end to end: log a session →
it shows up as verified data on a public page. This is your networking demo."
**Decisions of record:** ADR-002 (`docs/decisions/2026-05-28-donor-surface-profile-snapshot.md`)

---

## The fieldwork test (CLAUDE.md requirement)

After this ships, Matthew Ratz at Passion for Learning can log his Tuesday
tutoring sessions for a month (already possible), then click **Publish** on a
program and hand a donor a real URL — `understory.../programs/tuesday-reading-stars/`
— showing "12 sessions held, 18 students attending this month," each number
carrying a "derived from logged attendance" badge, alongside a short description
of the program he wrote. He stops emailing a hand-typed PDF of made-up-feeling
numbers and instead points funders at a page whose numbers he didn't type and
can't fudge. That page is the thing he shows people when he is networking for
funding — the concrete artifact this whole slice exists to produce.

If a slice below does not move toward *that page existing and being shareable*,
it is misscoped.

---

## Scope

**In:**
- `ProfileSnapshot` model + migration (per ADR-002 §2).
- Slug fields on `Program` and `Organization` (ADR-002 §6).
- Minimal publishable descriptive content: `Program.summary`, `Organization.description`/`location` (lean step-3 overlap — only the fields the public page renders).
- Snapshot build/publish service in `core/services/` deriving numbers from `attendance.queries`.
- `discovery` app: one public program page, browse-only, no auth, reads only published snapshots.
- Coordinator-side publish flow: preview ("this is how donors see you") + publish button, hung off the existing program detail page in `attendance`.
- Provenance badge component + a donor `base.html`.
- Tests: verification-chain (numbers trace to log), PII boundary (no `display_name` in payload), append-only/version semantics, idempotent publish.

**Out (explicitly deferred):**
- Discovery feed / browse-all / Compare (step 6 — needs the metric vocabulary).
- `MetricDefinition`/`OutcomeMetric` (lands with Compare; ADR-002 §4).
- Full org profile editor (only the fields the public page needs are added here; the rich editor is its own step-3 slice).
- AI-drafted narrative sections (step 5).
- Background queue (ADR-002 §5).
- Give-flow / fee (step 8).

---

## Prerequisite (not part of this slice, but blocks demoing it)

**`bootstrap_org` management command is missing.** `accounts.models` points
`create_superuser` at it, but it does not exist — there is no way to create the
first coordinator except editing the DB by hand, so nothing in the UI is
reachable for a live demo. Ship this first as a tiny standalone Sonnet task
(`accounts/management/commands/bootstrap_org.py`: create Org + coordinator User +
mint a magic link, print the login URL). One command, one test. **Not an Opus
task.**

---

## Data model (the escalation core — see ADR-002 §2)

`core/models.py` gains `ProfileSnapshot` exactly as ADR-002 specifies
(append-only, versioned, `supersedes` link, `status`, `payload` JSON,
`coverage_start/end`, `published_at/by`). `save()` override forbids mutating a
`PUBLISHED` row, matching `AttendanceRecord`.

`payload` shape (frozen on publish):
```json
{
  "program": {"name": "...", "summary": "...", "site_label": "..."},
  "org": {"name": "...", "description": "...", "location": "..."},
  "metrics": [
    {"key": "sessions_held", "label": "Sessions held",
     "value": 12, "unit": "sessions",
     "provenance": "derived", "window": "2026-05-01..2026-05-31"},
    {"key": "students_attending", "label": "Students attending",
     "value": 18, "unit": "students",
     "provenance": "derived", "window": "2026-05-01..2026-05-31"}
  ]
}
```
Numbers come only from `attendance.queries`; the builder never reads a
client-supplied value (ADR-002 §3).

Slugs: `Program.slug`, `Organization.slug` (unique, auto from name on save).

---

## Build order (slices — each ends with a visible artifact)

Per CLAUDE.md plan-then-build: this plan is the Opus output. Implementation is
**Sonnet against this plan**, except where a slice is flagged Opus. Stop and
update this plan if implementation reveals it is wrong; don't paper over it.

### Slice 0 — `bootstrap_org` (Sonnet, prerequisite)
Command + test. Makes the rest demoable. Independent; can land immediately.

### Slice 1 — Schema: `ProfileSnapshot` + slugs + descriptive fields (Sonnet, but Opus reviews the migration)
- Add `ProfileSnapshot`, `Program.slug/summary`, `Organization.slug/description/location`.
- Migration (data migration to backfill slugs for any existing rows).
- Append-only `save()` guard + model tests.
- **Deliverable:** schema in place; admin can create/inspect a snapshot. (No
  user-visible page yet — this is the one slice that leans infrastructural, kept
  minimal and immediately followed by Slice 2.)

### Slice 2 — Snapshot build/publish service (Sonnet)
- `core/services/snapshots.py`: `build_draft(program, window)` →
  `ProfileSnapshot(status=DRAFT)`; `publish(snapshot, user)` → freezes payload,
  sets version/`supersedes`, `PUBLISHED`.
- Numbers derived via `attendance.queries`; provenance recorded per metric.
- **Tests (required — verification chain):** payload numbers equal what the log
  yields; re-publishing same window is idempotent / produces a superseding
  version; no `display_name` ever appears in payload; published snapshot is
  immutable.
- **Deliverable:** `publish()` callable end-to-end; verifiable in a shell/test.

### Slice 3 — Public program page (`discovery` app) (Sonnet)
- New `discovery` app (imports `core` only). One view: `program_detail` by slug,
  404 if no current published snapshot. Reads `payload` only.
- Donor `base.html` (slightly more expressive than coordinator shell, per
  architecture §7.1) + provenance-badge include.
- Mount at `/programs/<slug>/`.
- **Deliverable:** a real public URL rendering verified metrics with badges. This
  is the networking-demo artifact.

### Slice 4 — Coordinator publish flow (Sonnet)
- On the existing `attendance` program detail page: a "Preview public page" view
  (renders the donor template against a draft) + a "Publish" POST that calls the
  service. Show current published version + "last published" state.
- Gated by `facilitator_or_coordinator_required`, scoped via `programs_visible_to`
  (publish is coordinator-only — confirm in open questions).
- **Deliverable:** the coordinator can publish from the UI; full loop is clickable.

---

## Model routing summary

| Slice | Model | Why |
|---|---|---|
| 0 bootstrap_org | Sonnet | Scaffolding/mgmt command. |
| 1 schema | Sonnet + Opus migration review | Multi-table schema is the escalation; ADR-002 fixes the design, Opus sanity-checks the migration. |
| 2 service | Sonnet | Logic against a fixed plan; verification-chain tests required. |
| 3 public page | Sonnet | Template/view work on a new but contract-bound app. |
| 4 publish flow | Sonnet | Coordinator-surface CRUD against existing patterns. |

If Slice 2's tests can't be made to prove "payload == log-derived" cleanly, that
is a signal the schema (Slice 1) is wrong — escalate back to Opus, don't force it.

---

## Tests required before merge (CLAUDE.md: verification chain + PII boundary)
- `test_snapshot_numbers_derive_from_log` — payload metrics equal `attendance.queries` output for the window.
- `test_snapshot_payload_has_no_pii` — no participant `display_name` in any payload.
- `test_published_snapshot_is_immutable` — `save()` on a PUBLISHED row raises.
- `test_republish_supersedes_not_mutates` — new version links via `supersedes`; old row unchanged.
- `test_publish_idempotent_same_window` — deterministic payload.
- `test_public_page_reads_only_published` — draft/withdrawn never render publicly; cross-program/no-snapshot → 404.

---

## Open questions for Chris (resolve before/at Slice 1)

1. **Publish permission:** coordinator-only, or facilitators too? (Plan assumes
   coordinator-only — publishing is an org-public act.)
2. **Default coverage window:** rolling current month? trailing 90 days?
   coordinator-chosen date range? (Plan assumes current month, matching the
   existing `program_month_stats` default; easy to widen.)
3. **Which metrics make the V1 public page** beyond sessions-held and
   students-attending? (e.g. cumulative students across the program's life,
   months-active.) Kept to the two derivable-today numbers unless you want more.
4. **Org page vs program page:** the architecture leads with program pages
   (donors fund programs). Confirm we ship the *program* page first and defer an
   org-level rollup. (Plan assumes program-first.)
5. **Lean-vs-full metric layer** (ADR-002 §4): confirm you're good deferring
   `MetricDefinition`/`OutcomeMetric` to the Compare step. Overridable here.
