# Plan — Grants ingest, slice 2: Tier-A solicitation sources (`pnd_rfp` + `grants_gov`)

**Date:** 2026-05-19
**Component:** 1 (ingestion + corpus versioning), build-order steps 2 and 3
**Scope:** Two Tier-A adapters that produce actual grant-solicitation records: `pnd_rfp` (Philanthropy News Digest RSS + source-page fetch) and `grants_gov` (federal opportunities — XML extract and/or REST API). End state: running `ingest_run --source pnd_rfp` and `ingest_run --source grants_gov` populates `OpportunityInstance` rows linked to `Funder` rows (creating new Funders on miss), with full provenance traceable through the event log to one or more `RawRecord` rows per opportunity.
**Goal in one sentence:** First slice that produces `OpportunityInstance` rows — slice 1 only built the funder registry.

This plan is the contract for the implementation session that follows. Implementation is Sonnet-tier work against this plan; deviations stop and update this file.

---

## 1. Adapter design — `pnd_rfp`

### 1.1 Source mechanics
- **Discovery feed:** `https://philanthropynewsdigest.org/rfps/rss` (verify exact URL during implementation — Candid has moved feeds before).
- **Cadence:** daily. RSS is small; full re-fetch each run is cheap.
- **Auth:** none. Rate-limit: 1 req/sec on the PND domain; same on funder source pages (each funder site is its own host, so the per-host throttle in `http.py` handles this automatically).
- **Two-stage fetch per item:**
  1. The RSS document itself (one fetch per run; one RawRecord per *changed* RSS body).
  2. For every RFP item that passes the geographic pre-filter (see §1.3), fetch the linked **funder source page** referenced in the item's `<link>`. Per spec line 645–647, the PND record is a hint; the funder's own page is the truth. The source page becomes a separate RawRecord on the same `OpportunityInstance`.

### 1.2 Adapter shape (conforms to existing `BaseAdapter`)
- `source_id = "pnd_rfp"`, `version = "0.1.0"`, `rate_limit_per_sec = 1.0`, `robots_compliance = "strict"`.
- `iter_fetch_tasks()`:
  - Yields one `FetchTask` for the RSS URL (mime `application/rss+xml`).
  - The follow-on per-item source-page fetches **cannot** be yielded up-front from `iter_fetch_tasks` because the URLs are only known after parsing the RSS body. Two options for handling this:
    - **(a) Two-pass run.** Override `run()` for this adapter: fetch+parse RSS first (producing a candidate-list of source URLs as a side product of `parse`), then drive a second loop of `fetch_one` calls for each candidate URL, parsing each into a single `opportunity_seen` event.
    - **(b) `parse()` re-enters fetch.** From inside `parse(raw_rss)`, call `self.fetch_one()` for each filtered item URL. Simpler control flow but couples parse with I/O, which the current base class avoids.
  - **Recommendation: option (a).** Override `run()` only for this adapter. Keep `parse()` pure (raw → events) by having the RSS-parse step emit an internal `pnd_item_discovered` event whose payload includes the candidate source URL, geo-scope text, and PND-side fields. The second loop reads those events back to drive source-page fetches. Alternative: add a `iter_fetch_tasks_followup(events)` hook to `BaseAdapter` and stop overriding `run()`. Both are defensible; pick during implementation. Either way, the change to base-class behavior must be a single named extension point and not a hack inside `pnd_rfp.py`.

### 1.3 Pre-filtering — geographic scope
Per spec section 7, before triggering a source-page fetch:
- Read `geographic_scope` text from the RSS item (PND publishes this as a structured field in their feed; verify the exact element name during implementation — likely `<category>` or a custom `<pnd:geo>` namespace; if it's free-text in the summary, fall back to a tokenized check on the item description).
- Pass the filter if any of these tokens appear case-insensitively: `"national"`, `"dc"`, `"district of columbia"`, `"md"`, `"maryland"`, `"va"`, `"virginia"`, `"dmv"`.
- Items that fail the filter: still store the RSS RawRecord (already done — one RSS RawRecord covers all items in that feed), but **do not** trigger the source-page fetch and **do not** create an `OpportunityInstance`. Log a `pnd_item_filtered` event with payload `{title, geo_scope_text, reason: "geo_filter"}` so the decision is auditable in the event log.

### 1.4 Tier-A field extraction at ingest
Tier A means typed fields are extracted at ingest. From the RSS item itself the adapter produces these fields straight onto an `OpportunityInstance` candidate, no LLM:

| PND RSS field | OpportunityInstance field |
|---|---|
| `<title>` | `title` |
| `<link>` | `notes['source_page_url']` (also becomes the second RawRecord's `fetch_url`) |
| `<pubDate>` or `<dc:date>` | `first_seen_at` (override with adapter `now()` if absent or in the future) |
| Deadline (parsed from item body / structured field) | `application_close_at` |
| Funder name (parsed from item body / structured field) | feeds `funder_name_raw` for resolution (see §4) |
| Geographic scope text | `geographic_scope` (stored as `{"raw_text": "..."}` for V1; structured later) |
| Summary / description | `notes['pnd_summary']` |

The linked **source page** is fetched as its own RawRecord but **not parsed in slice 2**. Per the Tier-A-at-ingest principle, the PND-side fields are the typed extraction. Deeper extraction from the funder's own page (full eligibility, award range, application route) is Component 2 / a future LLM-extraction slice. The source page lives in the corpus so a downstream extractor can run against it later.

This is a deliberate design choice: slice 2 keeps the OpportunityInstance "thin but real." Fields parseable from PND ship now. Fields requiring funder-page understanding wait for Component 2.

### 1.5 Idempotency
Three layers of dedup, ordered cheapest to most expensive:

1. **Content-addressed storage.** Same RSS body → same `content_sha` → `store.put` is a no-op on body, but a new `seen` event is still logged. Same for the source-page byte stream.
2. **RSS-item dedup inside the adapter.** Each RSS item has a `<guid>` (PND uses permalinks as GUIDs). Within a single run, skip already-processed GUIDs. Across runs, check the event log for a prior `pnd_item_discovered` event with the same `guid` and the same `application_close_at`. Re-emit only if the close date has changed (this is the signal that the funder updated the listing) — log a `pnd_item_updated` event in that case rather than `pnd_item_discovered`.
3. **OpportunityInstance dedup at materialization.** The materializer looks for an existing `OpportunityInstance` by `(source_id, pnd_guid)` and updates `last_seen_at` rather than creating a new row. Need to store `pnd_guid` in `notes`; see §3 for the model question.

The RSS feed re-publishing the same item is the dominant case. Re-stores should be cheap and observable in the event log, not silent.

### 1.6 New CorpusEvent types needed
- `OPPORTUNITY_SEEN` — emitted once per RSS item that passes filter (analogous to `funder_upserted` for `OpportunityInstance` upserts). Payload includes `source_id`, `pnd_guid`, the parseable fields, `funder_name_raw`, raw source URL.
- `OPPORTUNITY_FILTERED` — emitted for items that failed pre-filter (auditable).
- `OPPORTUNITY_UPDATED` — emitted when a re-seen item has changed fields.
- Reuse existing: `SEEN`, `PARSE_FAILED`, `ROBOTS_BLOCKED`.

(See §3.3 for the consolidated list across both adapters.)

---

## 2. Adapter design — `grants_gov`

### 2.1 Source mechanics — recommend XML extract for slice 2
Grants.gov exposes two paths:

1. **Daily XML extract.** A single zipped XML file containing every currently open opportunity. URL pattern (verify during implementation): `https://prod-grants-gov-chamel.s3.amazonaws.com/extracts/GrantsDBExtract{YYYYMMDD}v2.zip` or similar; the spec calls this "the canonical bulk path."
2. **REST API.** `https://api.grants.gov/v1/api/search2` and related endpoints. Returns JSON. Better for incremental queries; potentially throttled.

**Recommendation: XML extract for slice 2.** Reasoning:
- One fetch per day, ~5-30 MB zipped — well-behaved.
- No auth, no rate-limit risk, no need to track query state.
- Same shape as `irs_990pf` (XML parsing already wired via stdlib `xml.etree.ElementTree`).
- The REST API requires verifying current auth posture (grants.gov has shifted between key-free and key-required in the past); the XML extract has been stable.

**Tradeoff stated clearly:** the XML extract is point-in-time — opportunities closed in the previous 24h disappear from the next day's extract. That's fine for an active corpus (status-transition logic in spec §State transitions handles it), but it means we cannot replay the past from grants.gov bulk data alone. If a future slice needs historical federal opportunities (e.g., for Component 6 training), we'd need the REST API's date-range query or an external archive.

**Open question for Chris — confirm before implementation begins:** is "daily XML extract only" acceptable for slice 2, or do we want to dual-path (XML for bulk, REST for fill-in or for replay)? See §8.

### 2.2 Adapter shape
- `source_id = "grants_gov"`, `version = "0.1.0"`, `rate_limit_per_sec = 1.0` (only matters on the zip download — single request).
- `iter_fetch_tasks()`:
  - Yields one `FetchTask` for the daily XML extract zip URL.
  - That's it for slice 2. (REST-API path would yield N tasks; deferred.)
- `parse()`:
  - Unzip the body in-memory (`zipfile.ZipFile(io.BytesIO(body))`).
  - Stream-parse the XML (each `<Opportunity>` element processed independently — the extract can have thousands of records; iterparse with `clear()` keeps memory bounded).
  - For each opportunity element, apply pre-filter (§2.3). If it passes, emit `OPPORTUNITY_SEEN`. If it fails, emit `OPPORTUNITY_FILTERED` (per spec section 9: "store the raw, skip the OpportunityInstance creation" — the raw record is already stored; we additionally log the filter decision so the funder graph isn't lost to silent skips).
  - If the `Description` field is a PDF URL, queue a secondary fetch (see §2.5).

### 2.3 Pre-filtering — relevance gate
Per spec section 9. An opportunity passes if **all three** of these hold:

1. **EligibleApplicants** includes code `25` (nonprofit with 501c3) **or** code `12` (other nonprofit). The XML lists these as one or more `<EligibleApplicants>` elements with single-digit/two-digit codes. Empty / missing = treat as fail.
2. **CFDANumber** (now called Assistance Listing number) matches one of: starts with `84.` (Education), starts with `93.5` (HHS youth/family services), starts with `16.` (Justice). **Or** `CategoryOfFundingActivity` code is one of `E` (Education), `ED` (Education — sub), `HL` (Health). The OR between CFDA and category code is important — federal categorization is inconsistent.
3. **AwardFloor** is null/absent, **or** `AwardFloor < 250000`. Per spec: "don't drop on amount alone" — high-floor grants are still recorded as filtered (raw kept, no OpportunityInstance), not silently dropped.

Records that fail any of the three: store the raw, log `OPPORTUNITY_FILTERED` with the failed-rule reason in payload, **do not** create an `OpportunityInstance`. They remain in the corpus for the future funder graph.

### 2.4 Tier-A field extraction at ingest
From the XML extract, the adapter produces these typed fields straight onto `OpportunityInstance`:

| grants.gov XML field | OpportunityInstance field |
|---|---|
| `OpportunityID` | `notes['fed_opp_id']` (grants.gov internal numeric ID — different from the agency's number) |
| `OpportunityNumber` | `notes['fed_opp_number']` (agency-issued, e.g. `ED-2026-S-001`) |
| `OpportunityTitle` | `title` |
| `AgencyName` | feeds `funder_name_raw` for resolution; funder_type set to `govt_federal` |
| `CFDANumbers` (list) | `notes['cfda']` (list of strings) |
| `PostDate` | `first_seen_at` (override with adapter `now()` if absent) |
| `CloseDate` | `application_close_at` |
| `AwardCeiling` | `award_max` |
| `AwardFloor` | `award_min` |
| `EstimatedTotalProgramFunding` | `total_pool` |
| `ExpectedNumberOfAwards` | `notes['num_awards']` |
| `EligibleApplicants` (list of codes) | `notes['eligible_applicant_codes']` (kept as raw codes for now; structured EligibilityStruct deferred — see §3.2) |
| `FundingInstrumentType` | `notes['funding_instrument']` |
| `CategoryOfFundingActivity` | `subject_areas` (list of category codes; human-readable lookup deferred) |
| `AdditionalInformationURL` / `GrantorContactEmail` | `notes['contact']` |
| `Description` (URL to RFP PDF if present) | triggers secondary fetch (§2.5) |

`status` is set to `OPEN` at ingest. The status state machine (spec §State transitions) is a separate scheduled job and is **deferred to a later slice**.

### 2.5 PDF handling
`Description` is often a URL pointing to a PDF (the full RFP). For slice 2:
- **Fetch the PDF as a separate RawRecord** with its own `content_sha`. Same idempotent path as any other fetch. `mime_type = "application/pdf"`. Stored under `raw/grants_gov/.../<sha>.bin`.
- **Do not parse the PDF.** Per spec §9 Gotchas, PDF body extraction is a separate, model-versioned step (Component 2). The PDF is in the corpus; that's enough for slice 2.
- Link the PDF RawRecord to the `OpportunityInstance` via the `source_records` M2M field (the model already supports M2M). The `OpportunityInstance` ends up with two source records: the XML-extract bytes and the PDF bytes.
- **Skip if** the URL doesn't look like a PDF (no `.pdf` suffix and content-type comes back as HTML) — log `OPPORTUNITY_DESCRIPTION_NOT_PDF` and move on. We don't want to fetch arbitrary agency HTML in slice 2.
- **Rate-limit awareness:** PDFs can be large (50-200MB per spec). Hard-cap: skip and log if `Content-Length` (HEAD first) > 50 MB. Federal RFP PDFs rarely exceed 10 MB but the cap protects against runaway downloads.

### 2.6 Idempotency
- **XML extract content_sha.** Same daily extract bytes (in the unlikely case the same day is run twice) → no-op on body, new `seen` event.
- **Per-opportunity dedup.** Each `<Opportunity>` element has a unique `OpportunityID` (numeric). Within a run, skip dupes (shouldn't happen but defensive). Across runs, the materializer looks up `OpportunityInstance` by `notes['fed_opp_id']` (or a dedicated indexed field — see §3.1) and updates `last_seen_at` rather than creating a new row. Same pattern as PND.
- **PDF dedup.** Content-addressed; same PDF bytes from a different opportunity → same RawRecord, both `OpportunityInstance`s link to it via M2M.

### 2.7 New CorpusEvent types needed
Reuse the same set introduced for `pnd_rfp`: `OPPORTUNITY_SEEN`, `OPPORTUNITY_FILTERED`, `OPPORTUNITY_UPDATED`. Add one grants.gov-specific: `OPPORTUNITY_DESCRIPTION_NOT_PDF` (or fold into a generic `OPPORTUNITY_NOTE` event with payload `{kind: "description_not_pdf"}` — implementation call).

---

## 3. Model changes

### 3.1 `OpportunityInstance` — what's already there, what to add

The model already exists from slice 1 (it was scaffolded ahead of time per the slice-1 plan §2.3). Slice 2 is the first to actually create rows. **Audit before writing migrations** to confirm the shipped fields cover what slice 2 needs. Today's shape (`grants_ingest/opportunity.py`):

- `id`, `program`, `funder` (both nullable FKs — good)
- `title`, `application_open_at`, `application_close_at`, `rolling`
- `award_min`, `award_max`, `typical_award`, `total_pool`
- `program_type`, `eligibility (JSONField)`, `geographic_scope (JSONField)`, `subject_areas (JSONField list)`
- `status`, `first_seen_at`, `last_seen_at`
- `extraction_model_version`, `schema_version`, `provenance (JSONField)`
- `source_records` (M2M to RawRecord)

**Additions needed for slice 2:**

| Field | Why |
|---|---|
| `notes = JSONField(default=dict)` | Where slice 2 puts the unstructured-but-typed fields: `fed_opp_id`, `fed_opp_number`, `cfda`, `num_awards`, `funding_instrument`, `contact`, `pnd_guid`, `source_page_url`. The slice-1 plan's `OpportunityInstance` did not have a `notes` JSONField. Add now. |
| `source_id = CharField(max_length=64, db_index=True)` | The originating adapter (`pnd_rfp` or `grants_gov`). Needed for the per-source dedup query in the materializer and for downstream filtering. Cannot rely on `source_records[0].source_id` because some opportunities will have multi-source records over time. |
| `external_id = CharField(max_length=128, blank=True, db_index=True)` | A normalized external key for dedup: `f"grants_gov:{fed_opp_id}"` or `f"pnd_rfp:{pnd_guid}"`. Unique per `(source_id, external_id)`. This is the materializer's lookup key. Avoids querying inside a JSONField for the hot dedup path. |
| `funder_name_raw = CharField(max_length=255, blank=True, default="")` | Per spec §Cross-cutting, the candidate funder name produced by ingest before the resolver runs. Today there's no place to put it. Without this field, the resolver has no input. |

**Add a unique constraint:** `unique_together = [("source_id", "external_id")]` with the materializer using `update_or_create` on that key.

**Migration cost:** one new migration adding three fields and one constraint. No data backfill needed (no rows exist yet from prior slices).

### 3.2 `eligibility` / `EligibilityStruct` — explicitly deferred for slice 2
The spec's `EligibilityStruct` (org_type, geo_required, geo_excluded, budget_range_required, etc.) is the most consequential downstream contract and the easiest to get wrong by rushing. **Slice 2 stores raw codes only in `notes`** (`eligible_applicant_codes`, `cfda`, plus the PND geographic-scope free-text) and leaves the `eligibility = JSONField(default=dict)` field empty.

This is a deliberate punt: producing a real EligibilityStruct from grants.gov XML requires a lookup table for EligibleApplicants codes (25 → "501c3 nonprofit") and a normalized geo-required schema. Both are tractable but they're their own design problem. Slice 3 (or a dedicated "EligibilityStruct v1" slice between 2 and 3) does that work against the corpus slice 2 produces.

**What ships in slice 2:** raw codes in `notes`. What does **not** ship: structured `eligibility` field, FIPS geo encoding, normalized org-type taxonomy.

### 3.3 `CorpusEventType` — new enum values

Add to `grants_ingest/corpus_event.py`:

```python
OPPORTUNITY_SEEN = "opportunity_seen", "Opportunity seen"
OPPORTUNITY_UPDATED = "opportunity_updated", "Opportunity updated"
OPPORTUNITY_FILTERED = "opportunity_filtered", "Opportunity filtered"
```

(`OPPORTUNITY_DESCRIPTION_NOT_PDF` from §2.7 is a minor footnote; can be a payload kind under a generic `OPPORTUNITY_NOTE` if Chris prefers to keep the enum tight, or its own value. Implementation call.)

No removal or renaming of existing values. Backward compatible.

### 3.4 `Program` model — no rows yet
Slice 2 does not produce `Program` rows. Federal opportunities map roughly to programs (`OpportunityTitle` is often a program name + cycle), but conflating titles into program identity is the same kind of premature normalization the resolver was designed to avoid. For slice 2: every `OpportunityInstance` has `program=None`. A future slice introduces a program-resolver pass over the corpus, similar to the funder resolver, that promotes recurring opportunity-title patterns into Programs. This keeps slice 2's surface area small.

### 3.5 `Funder` upserts as a side effect of opportunity ingest
Per spec §Cross-cutting, an opportunity's funder is `funder_name_raw` at ingest, resolved later. In slice 2, the materializer's flow when handling an `OPPORTUNITY_SEEN` event:

1. Create or update the `OpportunityInstance` row keyed on `(source_id, external_id)`. Funder/program both null at this point.
2. **Do not** create a new `Funder` row inline from the opportunity. Funder creation belongs to the resolver pass.
3. The resolver (extended for slice 2) reads `OpportunityInstance.funder_id IS NULL` rows, runs `resolve_funder(funder_name_raw, ein=None)`:
   - Hit → log `RESOLVED` event, set `funder_id` on the OpportunityInstance.
   - Miss → log `RESOLVED` (with `confidence="none"`) **and** for `grants_gov` opportunities specifically, create a new `Funder` row with `funder_type=GOVT_FEDERAL` and `canonical_name = funder_name_raw`. Federal agencies are well-known and stable; creating Funders on first sighting is cheap and correct. For `pnd_rfp`, leave it on the manual-review queue — PND surfaces unfamiliar national funders and a wrong-auto-create is hard to undo.

This split (`grants_gov` auto-create funder on miss, `pnd_rfp` do not) is a workflow-fit call: federal agencies are a closed set, PND is a long tail. Worth flagging as an explicit decision in §8 / open questions in case Chris disagrees.

---

## 4. Management commands

### 4.1 Extend `ingest_run`, not add new commands
`ingest_run --source <id>` is already the single entry point. Slice 2 extends the `choices` list:

```python
parser.add_argument(
    "--source",
    required=True,
    choices=["propublica_np", "irs_990pf", "pnd_rfp", "grants_gov"],
)
```

…and adds two source-specific options:

- `--pnd-rss-url <url>` (override the default PND RSS URL, useful for testing against a saved fixture)
- `--grants-gov-extract-url <url>` (same, for the daily extract)

If these aren't provided, the adapter constructs the default URL itself (with today's date for grants.gov).

Inside `handle()`, dispatch to a new factory function that picks the adapter class. The slice-1 in-function if/elif is fine for two sources; for four it should move to a small dispatch dict. Refactor in the same commit that adds the new sources.

### 4.2 `resolve_entities` extension
Today the resolver only walks `HistoricalGrant.recipient_id IS NULL` rows (slice 1 work). Slice 2 adds an `OpportunityInstance.funder_id IS NULL` walk:

```python
parser.add_argument("--target", choices=["historical_grants", "opportunities", "all"], default="all")
```

For each opportunity row:
- Call `resolve_funder(opportunity.funder_name_raw, ein=None)`.
- Hit → set `funder_id`, log `RESOLVED`.
- Miss + `source_id == "grants_gov"` → create new `Funder(funder_type=GOVT_FEDERAL, ...)`, set `funder_id`, log `RESOLVED` with `confidence="created_from_funder_name_raw"`.
- Miss + other source → leave null, log `RESOLVED` with `confidence="none"`.

`resolution.py:resolve_funder` itself does **not** change — keep that function pure (no side-effects, no Funder creation). The Funder-creation policy lives in the management command, not in the resolver, so the resolver stays a single-purpose pure function.

### 4.3 No changes needed for slice 2
- `materialize` — handles new event types via the existing dispatch table after handlers are added. No CLI surface change.
- `snapshot_tag` — unchanged. Captures `max(CorpusEvent.id)` regardless of event types.
- `ingest_health` — extend its hand-rolled summary to include opportunity counts and per-source breakdown (`funders=29 opportunities_pnd=42 opportunities_grants_gov=350 ...`). Stub-level; the structured `IngestHealthSnapshot`-writing job is still deferred.
- `unresolved_queue` — works as-is once the query includes `OpportunityInstance` rows with `funder_id IS NULL`. Extend the query, not the CLI.

---

## 5. Materializer extension

`materialize.py` today dispatches on `FUNDER_UPSERTED`, `FUNDER_ENRICHED`, `HISTORICAL_GRANT_RECORDED`. Slice 2 adds:

- `OPPORTUNITY_SEEN` → `OpportunityInstance.objects.update_or_create(source_id=..., external_id=..., defaults={...})`. Sets/updates `last_seen_at=event.timestamp` and `first_seen_at=existing.first_seen_at or event.timestamp`. Links the event's `content_sha`-derived RawRecord to `source_records` (M2M `.add()`).
- `OPPORTUNITY_UPDATED` → finds the existing row by `(source_id, external_id)`, updates `application_close_at` and any other changed fields from payload, refreshes `last_seen_at`. If no existing row, falls back to the `OPPORTUNITY_SEEN` create path (defensive).
- `OPPORTUNITY_FILTERED` → no DB write. The event itself is the audit trail.
- `RESOLVED` for an opportunity_id (new payload shape — distinguish from existing recipient resolution via a `target` field in payload, e.g. `{"target": "opportunity", "opportunity_id": "...", "funder_id": "..."}`) → set `OpportunityInstance.funder_id` to the resolved funder UUID.

Idempotency: applying the same event sequence twice produces the same DB state. `update_or_create` on `(source_id, external_id)` guarantees no duplicate opportunity rows. M2M `.add()` is idempotent by Django default.

**Replay safety check** to write into the materializer tests: drop all `OpportunityInstance` rows, run `apply_events(since_event_id=0)`, assert the row count and shape match the prior state. Same invariant as slice 1.

---

## 6. Test fixtures plan

All synthetic. No real grant data, no real federal agency names that aren't in the public registry already, no real EINs that aren't IRS-reserved (`00-XXXXXXX`, `99-XXXXXXX`).

### 6.1 `pnd_rfp` fixtures
- `tests/grants_ingest/fixtures/pnd_rss_sample.xml` — a hand-crafted RSS 2.0 file with ~6 items spanning the filter cases:
  - 1 item with `national` in geo → passes filter.
  - 1 item with `DMV` → passes filter.
  - 1 item with `Texas` → filtered out.
  - 1 item with no geo field → filtered out (defaults to fail).
  - 1 item whose `<link>` points to a synthetic source page (test fixture URL).
  - 1 item that's a re-publish of an earlier item with the same GUID but a changed deadline → exercises the `OPPORTUNITY_UPDATED` path.
- `tests/grants_ingest/fixtures/pnd_source_page.html` — a stub HTML page for the source-page fetch. Content doesn't matter (slice 2 doesn't parse it), but a non-empty body is needed so `content_sha` is deterministic and stored.

### 6.2 `grants_gov` fixtures
- `tests/grants_ingest/fixtures/grants_gov_extract.zip` — a hand-crafted zip containing a synthetic `GrantsDBExtract.xml` with ~8 `<Opportunity>` elements:
  - 1 passing all three filter rules (eligible-applicant=25, CFDA `84.287`, AwardFloor `50000`) → produces an `OpportunityInstance`.
  - 1 with eligible-applicant=25 but CFDA `15.000` (not in our set) → filtered out.
  - 1 with eligible-applicant=01 (state govt) → filtered out (wrong applicant type).
  - 1 with eligible-applicant=25, CFDA `93.500`, AwardFloor `500000` → filtered out (too high).
  - 1 with all filters passing and a `Description` URL ending in `.pdf` → exercises the PDF-fetch branch.
  - 1 with a `Description` URL ending in `.html` → exercises the "not a PDF, skip" branch.
  - 1 with multiple `<EligibleApplicants>` codes including `25` → passes.
  - 1 with `Category Of Funding Activity = ED` but no CFDA → passes (the OR rule).
- `tests/grants_ingest/fixtures/grants_gov_fake_rfp.pdf` — a minimal valid PDF (5 bytes of header + "Hello"). Used to verify the PDF-fetch path, not for content extraction.

### 6.3 Coverage in scope vs. deferred
- **In scope:**
  - Each pre-filter rule has a positive and a negative test case.
  - `OPPORTUNITY_SEEN` event payload shape verified for each adapter.
  - Idempotency on re-run with same fixture (no duplicate rows, no duplicate events of the same type for same content_sha).
  - PND RSS dedup by GUID.
  - PDF RawRecord linked via M2M.
  - Materializer creates `OpportunityInstance` from `OPPORTUNITY_SEEN`.
  - Materializer applies `OPPORTUNITY_UPDATED` correctly.
  - Resolver creates a Funder on `grants_gov` miss; does not on `pnd_rfp` miss.
- **Deferred to slice 3+:**
  - Full EligibilityStruct extraction from XML.
  - PDF body parsing.
  - PND source-page parsing.
  - REST-API path for grants.gov.
  - State-transition state machine (close-date timing, `unreachable` → `withdrawn`).
  - Live integration tests against real PND and real grants.gov (one-shot manual verification on the final commit, mirroring slice 1's bug-bash run).

---

## 7. Task breakdown — 8 commits

Order is dependency-driven. Each step is a single reviewable commit.

1. **`feat(grants_ingest): add OpportunityInstance fields + new event types`**
   Migration adding `notes`, `source_id`, `external_id`, `funder_name_raw`, and `unique_together` to `OpportunityInstance`. Add `OPPORTUNITY_SEEN`, `OPPORTUNITY_UPDATED`, `OPPORTUNITY_FILTERED` to `CorpusEventType`. No adapter code yet. Migration tested against slice-1 state (no rows lost, no existing data to migrate).

2. **`feat(grants_ingest): materializer handlers for opportunity events`**
   Add `_apply_opportunity_seen`, `_apply_opportunity_updated` to `materialize.py`. Extend dispatch table. Idempotency test: apply same fixture twice → same row count. Replay-from-zero test included.

3. **`feat(grants_ingest): PNDRfpAdapter — RSS parsing + geo pre-filter`**
   Adapter file `grants_ingest/adapters/pnd_rfp.py`. RSS parser using stdlib `xml.etree.ElementTree`. Two-pass `run()` override (or `iter_fetch_tasks_followup` hook — pick during implementation, document the choice in the commit message). Fixture tests against `pnd_rss_sample.xml`. PNDRfpAdapter does NOT fetch source pages yet — that's the next commit. This keeps the diff reviewable.

4. **`feat(grants_ingest): PNDRfpAdapter — source-page fetch as secondary RawRecord`**
   Add the per-item source-page fetch behind the geo filter. Source page lives as a separate RawRecord, linked via the `OPPORTUNITY_SEEN` event's `source_records` list. Tests cover: filter blocks fetch; passing items trigger the fetch; second-run dedup.

5. **`feat(grants_ingest): GrantsGovAdapter — daily XML extract + pre-filter`**
   Adapter file `grants_ingest/adapters/grants_gov.py`. Zip download + in-memory iterparse. All three pre-filter rules. Emits `OPPORTUNITY_SEEN` for passes, `OPPORTUNITY_FILTERED` for fails. **Does not** fetch the Description PDF yet — that's the next commit.

6. **`feat(grants_ingest): GrantsGovAdapter — Description PDF fetch as secondary RawRecord`**
   Add the PDF-fetch branch. HEAD-then-GET with the 50MB cap. Skips non-PDF Description URLs with an event. M2M-links the PDF RawRecord to the OpportunityInstance via the `OPPORTUNITY_SEEN` payload.

7. **`feat(grants_ingest): resolver + ingest_run + ingest_health extensions`**
   Extend `resolve_entities` with `--target opportunities|historical_grants|all`. Add Funder auto-create policy for `grants_gov` misses inside the management command (not in `resolution.py`). Extend `ingest_run --source` choices to four. Refactor source dispatch to a small dict. `ingest_health` reports opportunity counts per source.

8. **`docs(grants_ingest): slice-2 handoff + live verification note`**
   README updates. Handoff doc at `docs/handoffs/2026-05-19-grants-slice2-complete.md` after the implementation runs a single live ingest against real PND RSS and a real grants.gov extract (same shape as slice-1's bug-bash run — small, manual, documented).

**Sizing check:** 8 commits, 4-7 days of focused Sonnet work against this plan. Fits the slice-1 cadence.

---

## 8. Open questions for Chris before implementation begins

Surface these now, not after Sonnet has started writing code. Each is a real branch in the design space.

### Q1. Grants.gov path — XML-only or dual-path?
**Recommendation in §2.1:** daily XML extract only for slice 2. **What this rules out:** any historical / closed-opportunity replay from grants.gov before our first ingest. **If you want dual-path:** add the REST API as a secondary fetch in this slice, ~+1 commit and one new auth open question (does grants.gov v2 require an API key in 2026? — verify during implementation; the spec was written assuming key-free).
**Default if you say nothing:** XML-only, REST deferred.

### Q2. Auto-create `Funder` from `grants_gov` opportunity miss?
**Recommendation in §3.5:** yes for `grants_gov` (federal agencies are a closed set, ~30 names), no for `pnd_rfp` (long tail, harder to undo wrong creates).
**Alternative:** never auto-create from opportunities; everything stays on the manual-review queue until a human (you) approves it. Cleaner verification chain, but pads slice 2 with ~30 hand-resolutions on first run.
**Default if you say nothing:** the asymmetric policy in §3.5.

### Q3. Two-pass adapter run (`pnd_rfp`) — extend `BaseAdapter` or override per-adapter?
The two-pass shape (RSS first, then per-item secondary fetches) is the first place a slice-2 adapter cannot be expressed in the slice-1 `BaseAdapter` contract. Two options:
- **(a)** Override `run()` only inside `PNDRfpAdapter`. No base-class change. Risk: when the next two-pass adapter lands (likely a `cf_*` portal), we'll override again, and a pattern emerges in copy-paste form.
- **(b)** Add a generic `iter_fetch_tasks_followup(events_so_far)` hook to `BaseAdapter`. One-time change. Risk: premature abstraction.

**Recommendation:** (a) for slice 2 — override `run()` in `pnd_rfp.py` with a comment pointing at this open question. If a third use case shows up in slice 3, lift the pattern.
**Default if you say nothing:** (a), per-adapter override.

### Q4. PND RSS URL and update cadence — verify before coding
The exact RSS URL has shifted between Candid's redesigns. Implementation must verify the current URL at the start of the slice and update this plan if it differs from `https://philanthropynewsdigest.org/rfps/rss`. Also: does PND publish a `lastBuildDate` or `ttl` we can use to skip fetches when nothing has changed? Worth a 10-min check during implementation.
**Default if you say nothing:** verify-then-code; treat the URL in §1.1 as provisional until checked.

### Q5. OpportunityInstance schema lock-in vs incremental growth
**§3.1 proposes** adding three fields (`notes`, `source_id`, `external_id`, `funder_name_raw`) in one migration. Is that the full set you want before any opportunity rows land in production, or are you comfortable letting it grow per source as slices 3+ add `cf_*` and `pf_*`?
The risk of locking the schema now: under-spec'd `notes` keys diverge per source and need a cleanup migration later. The risk of growing it: more migrations over time, but each one small.
**Recommendation:** lock the four new fields in §3.1; let `notes` keys grow per source (they're JSON and don't require migrations). Revisit when slice 4+ ships and we see what's accumulated.
**Default if you say nothing:** §3.1 as written.

### Q6. EligibilityStruct timing — slice 2, slice 3, or its own slice?
**§3.2 defers it.** Worth confirming you're OK punting until the corpus has both grants.gov and `cf_*` data — that gives the structured-eligibility design a more representative sample to schema against.
**Default if you say nothing:** §3.2 as written, defer to slice 3+ / its own focused slice.

### Q7. `RAW_OBJECT_STORE_FS_PATH` env default
Carried from the slice-1 handoff. Slice 2 will hit it the first time the implementer tries to run anything locally. Worth adding a `.env.dev.example` and a Django settings fallback (`/tmp/uc-corpus` or similar) before implementation starts.
**Default if you say nothing:** flag in the slice-2 handoff and let Chris decide.

---

## 9. Explicit out-of-scope

- No CF portal scraping (`cf_*`). Slice 4.
- No PF portal scraping (`pf_*`). Slice 6.
- No Wayback adapter. Slice 5.
- No 990-PF ObjectId unblock. Deferred until Component 6 work begins.
- No Playwright / JS rendering.
- No LLM extraction of anything.
- No Component 2 (extraction from raw HTML / PDF). The PND source page and the grants.gov RFP PDFs land in the corpus but their bytes are not parsed.
- No Component 6 / outcome-ranking work.
- No EligibilityStruct schema (raw codes only — see §3.2).
- No FIPS / structured geographic schema (free text only).
- No status state machine (open → unreachable → withdrawn). All slice-2 rows are `OPEN`.
- No `Program` rows.
- No donor surface visibility.
- No Railway cron wiring (still local-only — see slice-1 plan §9).
- No `IngestHealthSnapshot` row writer (still stub — see slice-1 §10).
- No Django admin views for unresolved queue (CLI export only).
- No production `.env` for env vars (slice-1 carry-over).

---

## 10. Dependency map

```
slice-1 (shipped)
       │
       ▼
[migration #7]   add notes/source_id/external_id/funder_name_raw to OpportunityInstance
       │         add OPPORTUNITY_* event types
       ▼
[commit #2]      materializer: opportunity event handlers
       │         (now anything emitting OPPORTUNITY_SEEN can land in the registry)
       ▼
       ├──────────── [commits #3,#4] PNDRfpAdapter (RSS → source-page fetch)
       │                       │
       └──────────── [commits #5,#6] GrantsGovAdapter (XML → PDF fetch)
                               │
                               ▼
                          [commit #7]  resolver + ingest_run + ingest_health
                               │
                               ▼
                          [commit #8]  live verification + handoff
```

The PND and grants.gov tracks are independent after commit #2 and can be split across two implementation sessions if context budget matters.

---

## 11. Spec compliance checklist (slice-2 specific)

- [ ] Tier-A typed-field extraction at ingest (spec line 38-46): PND RSS fields + grants.gov XML fields covered in §1.4 and §2.4.
- [ ] PND source page fetched as separate RawRecord (spec line 645-647): §1.1 step 2.
- [ ] PND geo pre-filter before source-page fetch (spec line 642-644): §1.3.
- [ ] Grants.gov pre-filter rules (spec line 743-751): §2.3.
- [ ] Grants.gov failed-filter records "store the raw, skip the OpportunityInstance creation" (spec line 751): §2.3 closing paragraph.
- [ ] Grants.gov PDF as separate raw record, not parsed at ingest (spec line 755-760): §2.5.
- [ ] `funder_name_raw` on candidate `OpportunityInstance` (spec line 841-842): §3.1.
- [ ] Resolver runs after raw extraction, not inline (spec line 842-843): §3.5 and §4.2.
- [ ] Idempotency on inbound channels (CLAUDE.md invariant #4): §1.5 and §2.6.
- [ ] Append-only event log (CLAUDE.md invariant #3): no changes to event log semantics; new event types are additions.
- [ ] Verification chain integrity (CLAUDE.md invariant #1): every `OpportunityInstance` traces back to one or more `RawRecord` rows via `source_records` M2M and to one or more `CorpusEvent` rows via `event_log` query by `external_id`.
- [ ] PII minimization (CLAUDE.md invariant #2): grant solicitations contain no participant data. Funder contacts are organizational. Stored in `notes['contact']` as-is. No PII boundary crossed.
- [ ] Workflow fit > schema elegance (CLAUDE.md invariant #5): EligibilityStruct deferred (§3.2) rather than half-built. Raw codes in `notes` until a real downstream consumer pulls on the schema.

---

*End of plan.*
