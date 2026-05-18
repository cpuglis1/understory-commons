# ADR-001: Ingestion infrastructure additions

**Date:** 2026-05-18
**Status:** Accepted
**Authors:** Chris

## Context

The lean-stack invariant in `CLAUDE.md` requires an ADR for any new
infrastructure beyond Django + Postgres + Railway. Component 1 of the grant
discovery system (ingestion + corpus versioning) introduces several pieces
that collectively expand the stack and warrant recording.

## Decision

The following infrastructure is added for grant corpus ingestion:

1. **Content-addressed object store for raw records.** Filesystem-backed in
   local dev (`/var/lib/uc-corpus/`), S3-backed in production
   (`s3://uc-corpus/`). Same directory layout in both. Switch is a config
   flag.

2. **Playwright** for JavaScript-rendered portals. Used only by adapters
   whose source config declares `render: js`. Plain `httpx` is the default.
   Not exercised in the first build-order slice (`irs_990pf` +
   `propublica_np`) — added when the first `cf_*` adapter lands.

3. **Scheduled scraper runners.** Implemented as Django management commands
   invoked by cron on Railway in v1. Cadence per source declared in the
   source register. Migrate to a job queue (Django-Q2 or RQ — see existing
   open question in `CLAUDE.md`) once adapter count justifies it.

4. **Corpus event log in the main app DB.** Append-only `CorpusEvent`
   table, same database as the rest of the Django ORM (Postgres in prod,
   SQLite in dev). Append-only enforced at the model layer (`save()`
   override raising on update), matching the existing
   `attendance.AttendanceRecord` pattern. Materialized derived rows
   (`Funder`, `Program`, `OpportunityInstance`) are rebuildable from the
   event log; the event log itself is the source of truth.

5. **Internet Archive Wayback Machine adapter** for off-cycle backfill and
   monthly sweep of registered funders. Uses CDX API; no auth. Out of scope
   for the first slice; documented here so the abstraction shape doesn't
   need to retroactively accommodate it.

6. **Daily ingestion-health metrics job.** Django management command that
   computes the metrics defined in the *Ingestion health metrics* section
   of the spec and writes to an `IngestHealthSnapshot` table.

## Consequences

- Ingestion runs as a separate service surface from the user-facing Django
  app. On Railway, this is a scheduled worker (cron-driven management
  command), not the web dyno.
- The corpus event log and the registry tables (`Funder`, `Program`,
  `OpportunityInstance`, `HistoricalGrant`) coexist in one database. The
  event log is the source of truth; registry rows are materialized from
  it and can be rebuilt by replaying events. No two-way sync, no
  cross-database joins to manage.
- Playwright adds ~500MB to the container image and noticeable CPU cost.
  Acceptable for ingestion (offline, scheduled); would be unacceptable in
  the user-facing web path. Build a separate image for the ingestion worker
  if image size becomes an issue.
- Filesystem-to-S3 migration is a config flip but requires backfilling the
  existing local corpus to S3 on first production deploy. Treat as a
  one-time migration script, not an incremental sync.
- The cron-driven approach has no retry semantics on failure beyond the
  next scheduled run. Acceptable for v1; revisit when adapter failures
  become a regular operational concern.

## Alternatives considered

- **Scrapy framework.** Rejected: heavier than needed for ten sources, and
  its abstractions assume parse-at-fetch which contradicts the Tier B/C
  raw-only commitment.
- **Separate SQLite database for the event log.** Considered (and
  initially leaned toward, for isolation from the main app DB). Rejected
  in favor of operational simplicity: a separate DB requires a Django
  database router, costs the ability to join event-log rows against
  registry rows, and complicates the test setup. Append-only enforcement
  at the model layer gives the same correctness guarantee without the
  multi-DB plumbing. Revisit if ingestion workload meaningfully impacts
  the user-facing app DB's availability — at that point isolation
  becomes worth the cost.
- **Per-source containers / microservices.** Rejected: overkill for
  solo-dev maintenance. One worker process per cadence (daily / weekly /
  quarterly) iterating over its sources is enough.
- **Replacing event log with Postgres triggers / outbox.** Rejected:
  ingestion runs in a process that may not have a live Postgres connection
  during long scrape sessions. The SQLite event log is local and durable
  to that.
