# Plan — Grants ingest, slice 1: funder registry from `irs_990pf` + `propublica_np`

**Date:** 2026-05-18
**Component:** 1 (ingestion + corpus versioning), build-order step 1
**Scope:** only `irs_990pf` and `propublica_np`. No `pnd_rfp`, no `cf_*`, no
`gov_*`, no Wayback, no Playwright, no PDF handling.
**Goal:** at the end of implementation, running
`python manage.py ingest_run --source propublica_np --seed-list dmv_foundations.yml`
followed by
`python manage.py ingest_run --source irs_990pf --from-seed-list`
produces a populated funder registry with verified EINs, addresses,
annual-giving figures, application-info text, and a historical-grant ledger.
Every row is content-addressed back to a raw record on disk and traceable
through the event log.

This plan is the contract for the implementation session that follows.
Implementation is Sonnet-tier work against this plan; deviations stop and
update this file.

---

## 1. Where the work lives

**Decision: new Django app `grants_ingest` inside this repo.** Same
codebase as `accounts` / `core` / `attendance`. Not a separate package, not
a separate repo.

Reasoning:

- Settings, env-var pattern (`python-decouple`), Postgres config,
  Anthropic client, and Railway deploy are already wired. A separate repo
  would duplicate all of that for solo-dev maintenance overhead with no
  benefit.
- The funder registry will be queried alongside `core.Organization` once
  recipient resolution lands (Component 2+). Same DB, same ORM keeps
  cross-references trivial.
- ADR-001 already commits to "ingestion runs as a separate service surface
  on Railway" — that's achieved by running a different process (`release`
  command + cron-invoked management command), not by separating the
  codebase.

**Open question flagged below:** if you have a stronger preference for
extraction to a separate repo (e.g. for licensing or open-sourcing the
ingest stack later), now is the moment. The cost of splitting later is
real but bounded.

**App boundary:** `grants_ingest` owns adapters, storage abstraction, the
event log, registry models, and management commands. It does **not** own:

- the user-facing coordinator/donor surface (lives in `core` / future
  `donors`)
- the AI extraction logic for Tier B/C sources (Component 2 — separate
  package when it lands)
- the resolver between `HistoricalGrant.recipient_id` and
  `core.Organization` (Component 2+ — out of this slice)

---

## 2. Models

Spec types are translated to Django below. Spec field names are kept where
possible. Annotations after each block call out where the spec's invariants
don't map cleanly to the ORM.

### 2.1 `Funder`

```python
class Funder(TimestampedModel):
    id = UUIDField(primary_key=True, default=uuid4)
    ein = CharField(max_length=9, null=True, unique=True, db_index=True)  # digits-only, no dash
    canonical_name = CharField(max_length=255)
    canonical_name_normalized = CharField(max_length=255, db_index=True)  # for exact-match resolver
    funder_type = CharField(max_length=32, choices=FunderType.choices)
    accepts_unsolicited = BooleanField(null=True)
    typical_award_min = DecimalField(max_digits=12, decimal_places=2, null=True)
    typical_award_max = DecimalField(max_digits=12, decimal_places=2, null=True)
    notes = JSONField(default=dict)  # see spec §1 fields-to-extract
```

`aliases: list[str]` is **not** a column on `Funder`. It's a related model:

```python
class FunderAlias(TimestampedModel):
    funder = ForeignKey(Funder, on_delete=CASCADE, related_name="aliases")
    raw = CharField(max_length=255)
    normalized = CharField(max_length=255, db_index=True)

    class Meta:
        unique_together = [("funder", "normalized")]
```

**Why a table, not ArrayField/JSONField.** The resolver looks up by
`normalized` on every funder candidate — that's the hot path. A separate
table gives a real index. ArrayField is Postgres-only (we want dev/SQLite
parity for tests), and JSONField needs a `__contains` query that won't use
an index on SQLite.

`historical_recipients: list[UUID]` from the spec is **dropped from V1**.
It's derived from `HistoricalGrant.funder_id` once recipient resolution
exists; storing it on `Funder` would be denormalized state that drifts.
Spec author noted this as deferred-by-implication; calling it out so it
doesn't reappear.

`typical_award_range: tuple[Decimal, Decimal]` becomes two scalar columns.
Tuples don't fit the ORM and `JSONField` would lose decimal precision on
SQLite.

### 2.2 `Program`

```python
class Program(TimestampedModel):
    id = UUIDField(primary_key=True, default=uuid4)
    funder = ForeignKey(Funder, on_delete=CASCADE, related_name="programs")
    canonical_name = CharField(max_length=255)
    canonical_name_normalized = CharField(max_length=255, db_index=True)
    # accumulated_eligibility intentionally omitted — see spec line 105-109
```

`aliases` again as a `ProgramAlias` related model. `historical_instances`
again dropped — derived from `OpportunityInstance.program_id`.

**No `Program` rows are created in this slice.** `irs_990pf` and
`propublica_np` produce funder-level data and historical grants, not
programs. Model exists so the FK from `OpportunityInstance` is satisfied
when later slices land. No migrations on the Program table after this slice
unless schema changes.

### 2.3 `OpportunityInstance`

```python
class OpportunityInstance(TimestampedModel):
    id = UUIDField(primary_key=True, default=uuid4)
    program = ForeignKey(Program, on_delete=PROTECT, null=True, related_name="instances")
    funder = ForeignKey(Funder, on_delete=PROTECT, null=True, related_name="instances")
    title = CharField(max_length=512)
    application_open_at = DateTimeField(null=True)
    application_close_at = DateTimeField(null=True)
    rolling = BooleanField(default=False)
    award_min = DecimalField(max_digits=12, decimal_places=2, null=True)
    award_max = DecimalField(max_digits=12, decimal_places=2, null=True)
    typical_award = DecimalField(max_digits=12, decimal_places=2, null=True)
    total_pool = DecimalField(max_digits=12, decimal_places=2, null=True)
    program_type = CharField(max_length=32, choices=ProgramType.choices)
    eligibility = JSONField(default=dict)  # EligibilityStruct, validated by Pydantic on save
    geographic_scope = JSONField(default=dict)
    subject_areas = JSONField(default=list)
    status = CharField(max_length=32, choices=OpportunityStatus.choices)
    first_seen_at = DateTimeField()
    last_seen_at = DateTimeField()
    extraction_model_version = CharField(max_length=64, default="")
    schema_version = CharField(max_length=32)
    provenance = JSONField(default=dict)  # ExtractionTrace
    source_records = ManyToManyField("RawRecord", related_name="opportunities")
```

**No `OpportunityInstance` rows are created in this slice either.** Model
shape is committed so subsequent slices don't churn migrations. The
`eligibility` JSONField gets a Pydantic schema (`grants_ingest.schemas.
EligibilityStruct`) validated in `save()`; the actual Pydantic model is
written when the first source that produces eligibility data lands. For
now, an empty Pydantic stub.

**Invariant mismatch flag.** Spec types `eligibility: EligibilityStruct`
as a hard struct. JSONField loses static typing. Mitigation: Pydantic
validation in `clean()` / `save()`. Acknowledging the gap — runtime
validation, not compile-time.

### 2.4 `HistoricalGrant`

```python
class HistoricalGrant(TimestampedModel):
    id = UUIDField(primary_key=True, default=uuid4)
    funder = ForeignKey(Funder, on_delete=CASCADE, related_name="historical_grants")
    funder_ein = CharField(max_length=9, db_index=True)
    tax_year = IntegerField(db_index=True)
    recipient_name_raw = CharField(max_length=512)
    recipient_address_raw = TextField(blank=True, default="")
    recipient_ein = CharField(max_length=9, null=True, db_index=True)
    recipient_id = UUIDField(null=True)  # nullable FK target lives in future org registry
    amount = DecimalField(max_digits=12, decimal_places=2)
    purpose = TextField(blank=True, default="")
    relationship_flag = CharField(max_length=64, blank=True, default="")
    source_record = ForeignKey("RawRecord", on_delete=PROTECT)

    class Meta:
        # Idempotency: re-parsing the same XML can't duplicate grant rows.
        unique_together = [("source_record", "recipient_name_raw", "amount", "tax_year")]
```

`recipient_id` is left as a plain `UUIDField` rather than a `ForeignKey`
because the target table (the future org registry) doesn't exist yet.
Switching to a real FK is a later migration.

**Invariant mismatch flag.** Spec's `recipient_name_raw` + EIN-or-fuzzy
matching is "soft identity" — Django's unique constraints are strict.
The `unique_together` above is the strictest "we have not seen this
recipient+amount+year on this filing twice" constraint that doesn't risk
false duplicates. Recipient identity itself remains soft (resolved later
into `recipient_id`).

### 2.5 `RawRecord`

```python
class RawRecord(models.Model):
    content_sha = CharField(max_length=64, primary_key=True)
    fetch_url = URLField(max_length=2048)
    fetched_at = DateTimeField(db_index=True)
    source_id = CharField(max_length=64, db_index=True)
    mime_type = CharField(max_length=128)
    content_ref = CharField(max_length=512)  # object store URI
    http_status = IntegerField()
    fetch_metadata = JSONField(default=dict)
```

`content_sha` is the primary key. No surrogate UUID. The model has no
`updated_at` and overrides `save()` to raise on update — append-only.

Append-only enforcement follows the same pattern as
`attendance.AttendanceRecord` already in the repo.

### 2.6 `CorpusEvent` (event log)

```python
class CorpusEvent(models.Model):
    id = BigAutoField(primary_key=True)
    timestamp = DateTimeField(db_index=True)
    event_type = CharField(max_length=32, choices=CorpusEventType.choices)
    source_id = CharField(max_length=64, db_index=True)
    content_sha = CharField(max_length=64, null=True, db_index=True)
    opportunity_id = UUIDField(null=True, db_index=True)
    funder_id = UUIDField(null=True, db_index=True)
    program_id = UUIDField(null=True, db_index=True)
    payload = JSONField(default=dict)
    actor = CharField(max_length=128)  # 'system:adapter_v0.3.1' or 'user:chris'

    class Meta:
        # Spec §Event log: indexed by (source_id, timestamp) and
        # (opportunity_id, timestamp).
        indexes = [
            models.Index(fields=["source_id", "timestamp"]),
            models.Index(fields=["opportunity_id", "timestamp"]),
        ]
```

Lives in the main app DB alongside the registry tables (ADR-001 revised).
`opportunity_id`, `funder_id`, `program_id` stay as plain `UUIDField`s
rather than `ForeignKey`s — events are logged *before* the
materializer creates the corresponding registry rows, and the spec's
soft-identity model means a referenced row may legitimately not exist
yet at write time. Strict FKs would force a write order that the
materializer doesn't want.

`save()` overridden to raise on update. Append-only, same pattern as
`attendance.AttendanceRecord`.

### 2.7 `CorpusSnapshot`

```python
class CorpusSnapshot(models.Model):
    tag = CharField(max_length=128, primary_key=True)  # 'corpus-2026-05-17'
    event_log_position = BigIntegerField()             # max event id at snapshot time
    object_store_manifest_ref = CharField(max_length=64)  # sha256 of the manifest
    created_at = DateTimeField()
    notes = TextField(blank=True, default="")
```

Lives in the main app DB along with everything else. `event_log_position`
is `max(CorpusEvent.id)` at snapshot time — captured by reading the event
log inside the same transaction that writes the snapshot row.

### 2.8 `IngestHealthSnapshot`

```python
class IngestHealthSnapshot(models.Model):
    id = BigAutoField(primary_key=True)
    captured_at = DateTimeField(db_index=True)
    source_id = CharField(max_length=64, db_index=True)
    metric = CharField(max_length=64)  # 'fetch_success_rate', 'parse_error_rate', etc.
    value = DecimalField(max_digits=10, decimal_places=4)
    alert_threshold_breached = BooleanField(default=False)
```

Lives in the main app DB.

### 2.9 Database

Single database (`default`) for everything: registry tables, event log,
snapshots, health metrics. Postgres in prod via `DATABASE_URL`, SQLite
in dev — the existing app setup. No router, no `event_log` database, no
multi-DB Django configuration. ADR-001 revised on 2026-05-18 to reflect
this.

Append-only enforcement on `CorpusEvent` and `RawRecord` is at the model
layer (`save()` overridden to raise on `pk` set), matching how
`attendance.AttendanceRecord` already does it.

---

## 3. Object-store abstraction

Lives at `grants_ingest/storage/`:

```python
# grants_ingest/storage/base.py

class RawObjectStore(Protocol):
    def put(self, content_sha: str, body: bytes, sidecar: dict) -> str:
        """Idempotent. Returns the URI under which body is stored.
        If content_sha already exists, the body write is skipped; the
        sidecar is *not* overwritten (caller's job to log a re-fetch
        event with new sidecar separately on the event log).
        """

    def get(self, content_sha: str) -> bytes: ...
    def get_sidecar(self, content_sha: str) -> dict: ...
    def exists(self, content_sha: str) -> bool: ...
    def iter_manifest(self) -> Iterable[str]:
        """Yield every content_sha present. Used by snapshot manifest hash."""

    def uri_for(self, content_sha: str) -> str:
        """Compute the URI without touching the backend."""
```

Layout (identical fs and S3):

```
{root}/raw/{source_id}/{yyyy}/{mm}/{sha256[:2]}/{sha256}.bin
{root}/raw/{source_id}/{yyyy}/{mm}/{sha256[:2]}/{sha256}.json
```

`{root}` is `file://{RAW_OBJECT_STORE_FS_PATH}` in dev,
`s3://{RAW_OBJECT_STORE_S3_BUCKET}` in prod.

Two implementations:

- `grants_ingest/storage/fs.py: FileSystemRawObjectStore`
- `grants_ingest/storage/s3.py: S3RawObjectStore` (uses `boto3`)

Selection driven by `RAW_OBJECT_STORE_BACKEND` env var: `fs` (default) or
`s3`. `python-decouple` reads it the same way existing settings keys do.

**Phasing note:** `boto3` is added to `pyproject.toml` but the S3
implementation is a thin pass-through (`put`/`get`/`exists` against
`boto3.client('s3')`). Not exercised in tests in this slice — fs tests
verify the protocol; S3 verified on first prod deploy. Calling out so it
doesn't get over-engineered.

---

## 4. Adapter shape

### 4.1 Base class

```python
# grants_ingest/adapters/base.py

class BaseAdapter:
    source_id: ClassVar[str]
    version: ClassVar[str]  # bumps trigger re-fetch eligibility, not auto-re-fetch
    rate_limit_per_sec: ClassVar[float] = 1.0
    robots_compliance: ClassVar[str] = "strict"

    def __init__(self, store: RawObjectStore, event_log: EventLogWriter):
        self.store = store
        self.event_log = event_log

    def iter_fetch_tasks(self, **kwargs) -> Iterable[FetchTask]:
        """Source-specific. Yields (url, expected_mime, extra_metadata)
        triples. Drives the outer loop."""
        raise NotImplementedError

    def fetch_one(self, task: FetchTask) -> RawRecord:
        """Calls _http_get with retry+rate-limit, computes sha,
        idempotent-writes to store, returns RawRecord row (creating
        if new). Always logs a 'seen' event regardless of whether the
        body was a new sha."""
        ...

    def parse(self, raw: RawRecord) -> list[CorpusEvent]:
        """Tier A only. Produces derived events (Funder upserts,
        HistoricalGrant rows, etc.). Tier B/C: returns []."""
        return []

    def run(self, **kwargs) -> AdapterRunResult:
        for task in self.iter_fetch_tasks(**kwargs):
            raw = self.fetch_one(task)
            for event in self.parse(raw):
                self.event_log.append(event)
        return AdapterRunResult(...)
```

Retry + rate-limit + robots-check live in `_http_get`, shared. Backoff:
exponential, capped at 3 attempts, jitter. Robots: parsed once per host
per run; on disallow, the task is skipped with a `seen` event of type
`robots_blocked`.

### 4.2 Concrete adapter: `ProPublicaNPAdapter`

- `source_id = "propublica_np"`, `version = "0.1.0"`.
- Auth: none.
- Rate limit: 1 req/sec.
- Inputs: seed list of EINs (`dmv_foundations.yml` in repo); optionally a
  state+NTEE search to discover EINs we don't already have.
- `iter_fetch_tasks`: yields one `GET /organizations/{ein}.json` per seed
  EIN, plus an optional `GET /search.json?state[id]=DC&ntee[id]=B` etc. to
  expand coverage. Search disabled by default — flag `--expand-search` to
  enable.
- `parse`:
  - JSON decode the raw record.
  - Emit `funder_upserted` event with: ein, name, NTEE, address,
    subsection code, latest revenue, filings index.
  - Materializer (see §4.3) consumes the event and writes/updates
    `Funder`.
- Idempotency: content_sha on the JSON bytes. Same response → same sha →
  storage write skipped, `seen` event still logged.
- Failure modes handled: 404 (EIN not found → `seen` event with status
  payload, no Funder upsert), 429 (rate-limited → back off and retry), 5xx
  (retry then escalate).

### 4.3 Concrete adapter: `IRS990PFAdapter`

- `source_id = "irs_990pf"`, `version = "0.1.0"`.
- Auth: none.
- Rate limit: 1 req/sec on ProPublica's XML URLs (the V1 fetch path); IRS
  bulk-XML path deferred.
- Inputs: the filings index produced by `ProPublicaNPAdapter`'s
  `funder_upserted` events. Run mode: `--from-seed-list` walks
  `dmv_foundations.yml`; `--from-funders` walks all funders in the DB.
- `iter_fetch_tasks`: yields one fetch per filing XML URL per seed funder.
  Default: most-recent filing only. `--all-filings` walks every filing in
  the index.
- `parse`:
  - Parse XML with stdlib `xml.etree.ElementTree`. No `lxml` dep.
    `defusedxml.ElementTree` if XML-bomb hardening matters — confirm
    during implementation; IRS XML is well-formed and not user-supplied
    so default stdlib is acceptable for V1.
  - Extract Part XV-1 rows → `historical_grant_recorded` events.
  - Extract Part XV-2 text + filer-level metadata →
    `funder_enriched` event.
  - Tag every event with `source_record_sha`.
- Idempotency: content_sha on the XML bytes; plus the `HistoricalGrant`
  `unique_together` constraint as a belt-and-braces.
- Failure modes handled: malformed XML (logged as `parse_failed` event,
  raw record retained), missing Part XV-1 (older 990 forms — logged and
  skipped).

### 4.4 Materializer

Events alone don't populate the registry tables. A separate component
reads new events and applies them:

```python
# grants_ingest/materialize.py

def apply_events(since_event_id: int = 0) -> int:
    """Reads CorpusEvent rows from event_log DB starting after
    since_event_id, dispatches to per-event-type handlers that
    write to the default DB. Returns the highest event id applied.
    Idempotent on re-run from the same since_event_id."""
```

Event handlers:

- `funder_upserted` → `Funder.objects.update_or_create(...)` keyed on EIN.
- `funder_enriched` → updates `notes` and `accepts_unsolicited` etc. on
  the existing Funder.
- `historical_grant_recorded` → `HistoricalGrant.objects.get_or_create(...)`
  keyed on the model's `unique_together`.
- `resolved` (entity-resolver output) → sets `funder_id` on linked
  unresolved records.

Run from the management command after each adapter run. The full event
stream is replayable: dropping every `Funder` / `HistoricalGrant` and
calling `apply_events(since_event_id=0)` rebuilds the registry from
events.

---

## 5. Entity resolution (exact-match-after-normalize)

Spec §Identity resolution at ingest. V1: zero fuzzy matching.

```python
# grants_ingest/resolution.py

def normalize_funder_name(raw: str) -> str:
    """Lowercase, strip punctuation, strip suffixes (foundation, fund,
    trust, inc, incorporated, the), collapse whitespace."""
    ...

def resolve_funder(name_raw: str, ein: Optional[str]) -> ResolutionResult:
    """1. If ein given and matches a Funder.ein -> exact match.
       2. Else normalize name, exact-match against Funder.canonical_name_normalized.
       3. Else exact-match against FunderAlias.normalized.
       4. Else miss -> ResolutionResult(funder_id=None, confidence='none').
       Each call emits a 'resolved' event."""
```

Run via `python manage.py resolve_entities --source <id>`:

- Walks unresolved `HistoricalGrant.recipient_id` (None) rows or
  `OpportunityInstance.funder_id` (None) — in this slice, the latter
  doesn't exist yet, so this is exercised mostly on recipient lookups,
  which depend on the IRS BMF (out of scope for this slice).
- For this slice, the resolver's primary job is to deduplicate `Funder`
  records: if `ProPublicaNPAdapter` and `IRS990PFAdapter` both produce a
  Funder candidate for the same EIN, the materializer's
  `update_or_create` on EIN handles it. The resolver runs the
  name-and-alias path on Funders missing an EIN (rare in this slice;
  every ProPublica record has one).

Manual-review queue: a SQL query exposed as
`python manage.py unresolved_queue --output csv`. UI deferred.

---

## 6. Management commands

All in `grants_ingest/management/commands/`:

| Command | Purpose |
|---|---|
| `ingest_run --source <id> [--seed-list path] [--from-seed-list] [--from-funders] [--all-filings] [--expand-search]` | Runs one adapter end-to-end: fetch → store → events → materialize. |
| `ingest_run_all_due [--cadence daily|weekly|quarterly]` | Iterates adapters whose cadence matches and runs each. Cron entry point. Not used in this slice (only two adapters), but ships with the slice to lock the interface. |
| `materialize [--since-event-id N]` | Re-applies events to derived tables. Idempotent. |
| `resolve_entities [--source <id>] [--dry-run]` | Runs the resolver. |
| `unresolved_queue [--output csv|stdout]` | Manual-review dump. |
| `snapshot_tag <tag> [--notes "..."]` | Records a `CorpusSnapshot` row: captures `max(event.id)` and computes the object-store manifest hash. |
| `ingest_health` | Computes the daily metrics, writes `IngestHealthSnapshot` rows. |

Cron entries (Railway) are deferred until the next slice — see
"Railway-vs-local" open question below.

---

## 7. Test approach

CLAUDE.md policy: tests required for code touching the verification chain
or the PII boundary; coordinator-surface CRUD tests are phase-3. This
slice is entirely verification-chain code, so test coverage is required
on the load-bearing pieces. **Synthetic fixtures only — no real EINs, no
real filing data.**

### In scope for this slice

| Area | Tests |
|---|---|
| Content-addressed storage | put/get/exists round-trip on FS impl; sidecar separate from body; second put with same sha is a no-op on body; manifest iteration. |
| Sha computation | Same bytes → same sha across multiple `put` calls; different bytes → different sha. |
| `RawRecord` append-only | `.save()` on an existing row raises. |
| `CorpusEvent` append-only | Same. |
| `BaseAdapter._http_get` | Rate limit honored (mock clock, assert sleep call counts); retry on 5xx; abort on 4xx (other than 429). |
| `BaseAdapter.fetch_one` idempotency | Two calls with the same body → one stored object, two `seen` events. |
| `ProPublicaNPAdapter.parse` | Synthetic JSON fixture → emits expected `funder_upserted` event with all spec'd fields. NTEE / subsection codes flow through. |
| `IRS990PFAdapter.parse` | Synthetic 990-PF XML fixture (hand-crafted, fake EIN like `99-XXXXXXX`) → expected `historical_grant_recorded` events + one `funder_enriched`. |
| `materialize.apply_events` | Same events applied twice produce the same registry state (idempotent). Replay from zero recreates state. |
| `resolve_funder` | Normalization rules: "The Smith Foundation, Inc." === "smith". EIN match wins over name match. Alias match works after a `FunderAlias` row is added. |
| Snapshot tagging | `snapshot_tag` captures the right `event_log_position` and a stable manifest hash for a fixed object store. |

### Out of scope this slice (deferred)

- Live HTTP against ProPublica or IRS. A single `@pytest.mark.live` test
  exercises a real ProPublica call as a smoke check, but it's opt-in and
  not run in CI.
- S3 storage backend. The interface tests cover the FS impl; the S3 impl
  is verified on first prod deploy.
- PDF parsing (`irs_990pf` pre-2012 PDFs are out of scope per spec
  §Gotchas).
- Robots blocking / 429 handling against real hosts. Mock-based tests
  cover the code path.
- Full eligibility-struct schema tests — no source in this slice produces
  one.

### Fixture rules

- Every EIN in fixtures is `99-XXXXXXX` or `00-XXXXXXX` (IRS reserves
  these). Document this in `tests/grants_ingest/conftest.py`.
- Every funder name in fixtures is obviously synthetic ("Test Foundation
  for Synthetic Things").
- Recipient names in `HistoricalGrant` fixtures: same rule.

---

## 8. Implementation task breakdown

Each step ends in a single reviewable commit. Order is dependency-driven —
don't reorder without checking what unblocks what.

1. **`feat(grants_ingest): scaffold app`**
   App skeleton, `INSTALLED_APPS` entry, empty `apps.py`, `urls.py` stub,
   `models.py` empty, `management/commands/` empty, top-level docstring.
   No migrations yet.

2. **`feat(grants_ingest): object store interface and FS implementation`**
   `storage/base.py`, `storage/fs.py`, env-var wiring in
   `understory_commons/settings/base.py`, tests for round-trip and
   idempotency.

3. **`feat(grants_ingest): RawRecord model + append-only enforcement`**
   Model, migration, save-override, tests. Adds `httpx` to deps
   (confirm version during implementation). No `lxml` — stdlib
   `xml.etree.ElementTree` for the 990-PF parser.

4. **`feat(grants_ingest): CorpusEvent model`**
   Model in the default DB, migration, append-only `save()` override,
   append-only test, indexes per spec.

5. **`feat(grants_ingest): Funder, FunderAlias, Program, ProgramAlias models`**
   Models, migrations, FunderType / ProgramType / OpportunityStatus
   enums, normalized-name field, basic CRUD tests.

6. **`feat(grants_ingest): HistoricalGrant model`**
   Model, migration, idempotency-on-source_record test.

7. **`feat(grants_ingest): OpportunityInstance + CorpusSnapshot + IngestHealthSnapshot models`**
   Models and migrations — no rows produced this slice, but the schema
   ships now to avoid migration churn.

8. **`feat(grants_ingest): BaseAdapter, HTTP utilities, retry + rate-limit`**
   `adapters/base.py`, `adapters/http.py`, robots-txt cache, tests with
   `httpx.MockTransport`.

9. **`feat(grants_ingest): materializer`**
   `materialize.py`, event handlers for `funder_upserted`,
   `funder_enriched`, `historical_grant_recorded`, idempotency tests.

10. **`feat(grants_ingest): entity resolver (exact-match-after-normalize)`**
    `resolution.py`, `resolve_entities` command, tests on normalization
    edge cases.

11. **`feat(grants_ingest): ProPublicaNPAdapter`**
    Adapter, synthetic fixtures, parse tests, dry-run end-to-end test
    using `MockTransport`.

12. **`feat(grants_ingest): IRS990PFAdapter`**
    Adapter, synthetic XML fixtures, parse tests, dry-run end-to-end
    test.

13. **`feat(grants_ingest): management commands`**
    `ingest_run`, `materialize`, `snapshot_tag`, `unresolved_queue`,
    `ingest_health` (the health command can ship as a stub that emits
    zeroed metrics — refine when alert thresholds matter).

14. **`feat(grants_ingest): DMV foundation seed list`**
    `grants_ingest/seeds/dmv_foundations.yml` with the ~30-50 EINs from
    spec §4 starter list. Verified during implementation by running the
    pipeline once locally.

15. **`docs(grants_ingest): usage notes + handoff`**
    Short README in `grants_ingest/` covering env vars, the cron stub,
    how to refresh the registry. Handoff doc for the next slice
    (`pnd_rfp`).

Total: 15 commits. Estimated 4-7 days of focused work for a Sonnet
implementation pass with this plan as input.

---

## 9. Resolved decisions

All five questions resolved 2026-05-18 (same session that produced this
plan). Recording so the next implementation session doesn't relitigate:

1. **Repo layout.** Same repo, new Django app `grants_ingest`. Confirmed.

2. **Event log database.** Lives in the main app DB, **not** a separate
   SQLite file. ADR-001 revised to match. Simpler operationally; no DB
   router. Append-only enforced at the model layer.

3. **Railway vs local.** Local-only for this slice. Cron wiring deferred
   until ≥3 adapters and a daily-cadence one.

4. **Spec location.** Moved to `docs/specs/grant_ingestion.md`.

5. **XML parsing library.** Stdlib `xml.etree.ElementTree`. No `lxml`
   dependency.

---

## 10. What this plan does NOT cover

- Any source other than `irs_990pf` and `propublica_np`.
- Tier B/C raw-only handling (no source in this slice is Tier B/C).
- Wayback / off-cycle backfill.
- Playwright / JS rendering.
- LLM-based extraction (Component 2).
- Donor-surface visibility of any of this data.
- Recipient resolution into a future `core.Organization`-adjacent
  registry.
- A Django admin UI for the manual-review queue (CLI export only).

Anything in the above list that becomes urgent during implementation
should stop the work and trigger a plan update, not a quiet scope
expansion.
