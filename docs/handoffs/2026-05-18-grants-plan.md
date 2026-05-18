# Handoff — Grants ingest, planning session

**Date:** 2026-05-18
**Model:** Opus 4.7 (planning, no code)
**Phase:** new component (Grants ingest, Component 1, build-order slice 1)
**Next session target:** Sonnet, implementation against the plan, commit-by-commit per §8

---

## What shipped

- `docs/decisions/2026-05-18-ingestion-infrastructure.md` — ADR-001
  extracted from the spec's appendix. Status: Accepted. Codifies the
  filesystem/S3 object store, Playwright (deferred), cron-driven
  management commands, SQLite event log, Wayback adapter (deferred),
  and daily health metrics.
- `docs/plans/2026-05-18-grants-ingest-funder-registry.md` — full
  implementation plan for the first build-order slice (`irs_990pf` +
  `propublica_np` → working funder registry). 15 commits, each
  reviewable in isolation. Models, storage interface, adapter shape,
  management commands, test scope, and explicit out-of-scope list.

## What's queued

The implementation session that follows. Run order is the task
breakdown in §8 of the plan. Sonnet-tier, modulo the model-routing
escalation triggers in CLAUDE.md (one of which — "schema or data-model
changes that touch more than one table" — is technically tripped by
commits 3-7; the plan exists precisely so the schema is settled and
each migration commit is mechanical translation, not design).

If commits 3-7 surface a real schema-design question (not just typing),
stop and escalate back to Opus rather than papering it over.

## Decisions resolved this session

All five questions raised in the plan's first draft were resolved
before commit. Recording here so the next session doesn't relitigate:

1. **Same repo.** New Django app `grants_ingest` inside this repo.
2. **Event log in main app DB.** Not a separate SQLite file. ADR-001
   revised in place to match (decision #4 rewritten; the
   "Alternatives considered" entry flipped to record SQLite-isolation
   as the rejected alternative).
3. **Local-only first slice.** Railway worker / cron wiring deferred
   until ≥3 adapters and a daily-cadence one.
4. **Spec moved** from repo root to `docs/specs/grant_ingestion.md`.
5. **Stdlib XML parsing.** `xml.etree.ElementTree`, no `lxml` dep.

## Non-blocking, but worth noting

- The CLAUDE.md "Current phase" section still reads "Phase 1 — Scaffold
  + Attendance MVP." It should be updated when the grants-ingest slice
  starts execution — phase context is part of the routing signal and
  stale phase context is worse than no phase context (per CLAUDE.md
  itself).
- The seed list of DMV foundation EINs (commit 14) needs human
  curation: cross-checking against recent 990-PFs is the spec's
  prescription. ~30-50 EINs. Plan to spend an evening on this; it's
  the entry point of the whole pipeline.
- No new infrastructure (Redis, Kafka, queue lib) is introduced. The
  background-job library decision (Django-Q2 vs RQ) remains deferred
  per CLAUDE.md.

## Files touched this session

- `docs/decisions/2026-05-18-ingestion-infrastructure.md` (new)
- `docs/plans/2026-05-18-grants-ingest-funder-registry.md` (new)
- `docs/handoffs/2026-05-18-grants-plan.md` (this file, new)
- `docs/dev-log.md` (one-line append)

No code changes. No migrations. No model edits.
