# grants_ingest

Funder registry and grant corpus ingest pipeline for Understory Commons.

Fetches 990-PF filings (IRS e-file XML) and organization profiles (ProPublica Nonprofit Explorer), stores raw content in a content-addressed object store, emits append-only CorpusEvents, and materializes a queryable Funder/HistoricalGrant registry.

---

## Architecture overview

```
Adapter (fetch) → RawObjectStore (SHA-keyed blobs)
                → CorpusEvent log (append-only)
                → materialize() → Funder / HistoricalGrant tables
                                → resolve_entities → recipient_id FK
```

All derived state (Funder, HistoricalGrant) can be rebuilt by replaying CorpusEvents from scratch. The event log is the source of truth.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `RAW_OBJECT_STORE_BACKEND` | `fs` | `fs` or `s3` |
| `RAW_OBJECT_STORE_FS_PATH` | `/var/lib/uc-corpus` | Root dir for filesystem backend |
| `RAW_OBJECT_STORE_S3_BUCKET` | *(empty)* | S3 bucket name for s3 backend |

For local dev, the filesystem backend with a writable path is sufficient. S3 is wired but untested in slice 1.

---

## Management commands

### `ingest_run`
Run one adapter end-to-end: fetch → store → log events → materialize.

```bash
python manage.py ingest_run --source propublica_np
python manage.py ingest_run --source irs_990pf --from-funders
python manage.py ingest_run --source irs_990pf --from-seed-list --all-filings
```

### `materialize`
Re-apply CorpusEvents to derived registry tables. Idempotent.

```bash
python manage.py materialize
python manage.py materialize --since-event-id 1042
```

### `resolve_entities`
Run entity resolver over unresolved `HistoricalGrant.recipient_id` rows.

```bash
python manage.py resolve_entities
python manage.py resolve_entities --dry-run
python manage.py resolve_entities --source irs_990pf
```

### `unresolved_queue`
Dump unresolved rows for manual review.

```bash
python manage.py unresolved_queue
python manage.py unresolved_queue --output csv > unresolved.csv
```

### `snapshot_tag`
Record a named CorpusSnapshot (max event id + manifest hash).

```bash
python manage.py snapshot_tag corpus-2026-05-18 --notes "post-DMV refresh"
```

### `ingest_health`
Print live health metrics (funder count, grant count, resolution rate, last event id).

```bash
python manage.py ingest_health
```

---

## Seed list

`grants_ingest/seeds/dmv_foundations.yml` contains ~30 DMV-region foundation EINs. To refresh the funder registry:

```bash
python manage.py ingest_run --source propublica_np
python manage.py ingest_run --source irs_990pf --from-funders
python manage.py resolve_entities
python manage.py snapshot_tag corpus-$(date +%Y-%m-%d)
```

---

## Cron stub

No background job runner is wired in slice 1. The refresh sequence above is intended to run as a scheduled Railway cron or Django management task. Cron integration is deferred to slice 2 — see `docs/plans/` for the next-slice plan.

---

## Entity resolution

`grants_ingest/resolution.py` — exact-match resolver, no fuzzy matching in V1:

1. EIN match (strips dashes)
2. Canonical name normalized match
3. FunderAlias normalized match
4. Miss → `confidence='none'`, row stays unresolved

Unresolved rows accumulate in `HistoricalGrant.recipient_id = NULL`. Use `unresolved_queue` to export for manual alias registration, then re-run `resolve_entities`.

---

## Tests

```bash
pytest tests/grants_ingest/
```

All tests use synthetic EINs (`99-XXXXXXX` / `00-XXXXXXX` range) and MockTransport for HTTP — no live network calls in CI.
