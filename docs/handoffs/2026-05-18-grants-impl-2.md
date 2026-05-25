# Handoff — grants_ingest slice 1, implementation session 2

**Date:** 2026-05-18
**Branch:** `feat/grants-ingest-slice1`
**Model:** claude-sonnet-4.6
**Session:** Second and final implementation session for this slice

---

## What shipped this session

Continuing from session 1 (commits 1–8 landed), this session completed commits 9–15:

| Commit | SHA | Description |
|---|---|---|
| 9 | fadf070 | Entity resolver (exact-match-after-normalize) |
| 10 | dc91f55 | Materializer — CorpusEvent → Funder/HistoricalGrant |
| 11 | 847ca3b | BaseAdapter, HTTP utils, retry + rate-limit |
| 12 | 1e2ca0c | ProPublicaNPAdapter |
| 13 | 41fd09a | IRS990PFAdapter |
| 14 | d4a8cf7 | Management commands (6 commands) |
| 15 | 163f635 | DMV seed list (~30 EINs) |

Plus this session: `grants_ingest/README.md` (this commit).

---

## What the slice delivers (full picture)

A working funder-registry ingest pipeline:

1. **Object store** — content-addressed, SHA-keyed blobs; FS backend wired; S3 stub ready
2. **Append-only models** — RawRecord, CorpusEvent (save() override raises on update)
3. **Registry tables** — Funder, FunderAlias, Program, HistoricalGrant (derived from events)
4. **Adapters** — ProPublica Nonprofit Explorer (org profile JSON), IRS 990-PF (XML, namespace-aware)
5. **Materializer** — idempotent event replay; `--since-event-id` for incremental runs
6. **Entity resolver** — exact-match: EIN → canonical name → alias; no fuzzy in V1
7. **CLI** — 6 management commands covering full operator workflow
8. **Seed list** — ~30 DMV foundation EINs; carry verification notes; not authoritative as-is

---

## Design decisions made during implementation

- **CorpusEvent.content_sha** uses `blank=True, default=""` (empty string) not `null=True`, to sidestep the ruff DJ001 + black formatting conflict. Empty string = no associated blob (for non-fetch events); treat as sentinel.
- **Funder.ein** keeps `null=True` (genuine NULL needed — multiple funders may have no EIN). Per-file ruff ignore in `pyproject.toml`.
- **IRS 990-PF namespace handling** — adapter tries `{http://www.irs.gov/efile}ElementName` first, falls back to bare tag. Real e-file XML uses the namespace; test fixture uses bare tags. Both work.
- **Test directory** — no `__init__.py` in `tests/grants_ingest/`; adding one causes pytest to try importing as `grants_ingest.test_*` (collision with app module name).
- **ingest_health** is a counting stub. When alert thresholds are defined (slice 2+), extend to emit Prometheus metrics or post to a monitoring endpoint.

---

## Known gaps / deferred to slice 2

- **S3 backend untested** — wired and type-correct; needs integration test against localstack or real bucket
- **Cron / scheduler** — no background job runner. Refresh sequence is manual CLI for now. Pick Django-Q2 or RQ in slice 2, document in `/docs/decisions/`
- **Fuzzy entity resolution** — V1 is exact-match only. Unresolved rows accumulate; export with `unresolved_queue --output csv` for manual alias registration, then re-run `resolve_entities`
- **Seed list curation** — ~30 EINs are a scaffold, not a curated list. Several flagged as needing ProPublica/BMF verification before use in production runs
- **Slice 2 plan** — not yet written; scope TBD from fieldwork + what the coordinator surface actually needs from the funder registry

---

## How to run locally

```bash
# First-time setup
python manage.py migrate

# Fetch ProPublica profiles for seed EINs
python manage.py ingest_run --source propublica_np

# Fetch 990-PF XMLs for funders now in the DB
python manage.py ingest_run --source irs_990pf --from-funders

# Entity resolution pass
python manage.py resolve_entities

# Tag a snapshot
python manage.py snapshot_tag corpus-2026-05-18

# Health check
python manage.py ingest_health
```

---

## Tests

```bash
pytest tests/grants_ingest/ -v
```

All tests pass with MockTransport; no live HTTP required.

---

## Next session context

Start next session with this handoff note as initial context. Slice 2 scope is undefined — read `/docs/plans/` and the ADR, then plan with Opus before coding.
