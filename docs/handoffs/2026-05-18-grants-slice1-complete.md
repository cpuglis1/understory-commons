# Slice 1 completion note — grants_ingest live verification

**Date:** 2026-05-19
**Branch:** `feat/grants-ingest-slice1`
**Model:** claude-sonnet-4-6
**Scope:** Live API verification of the cleaned production seed against ProPublica Nonprofit Explorer + IRS 990-PF. All 5 bug-bash fixes from commits `744ddf0`–`23ec779` are in place. No code was modified this session.

---

## Run summary

| Command | Result | Notes |
|---|---|---|
| `ingest_run --source propublica_np` | fetched=29 stored_new=29 parse_errors=0 robots_blocked=0 | All 29 seed EINs resolved to real orgs |
| `ingest_run --source irs_990pf --from-funders` | fetched=0 stored_new=0 | Blocker — see Bug 7 |
| `resolve_entities` | Resolved=0 Missed=0 | Expected — HistoricalGrant table empty |
| `snapshot_tag corpus-2026-05-18-live-clean` | event_log_position=121 manifest=e236e4e2792a... | ✓ |
| `ingest_health` | funders=29 grants=0 events=58 last_id=121 | ✓ |

**Pre-run state:** DB tables cleared (grants_ingest only); object store retained 3 blobs from prior bug-bash run. Of the 3 retained blobs: Philip L. Graham Fund (EIN 526051781) was re-used by this run (content-identical response, `put()` skipped write, new RawRecord created via DB check), AWF and the error JSON blob are now orphaned on disk — harmless.

**Production seed:** 29 EINs (10 DC, 10 MD, 5 VA, 4 national-with-DMV-activity).

**Approximate runtime:** propublica_np ~45 s at 1 req/sec; irs_990pf instantaneous (0 fetches).

---

## End-to-end verification

The following are signed off as working against real data:

1. **ProPublica API connectivity.** All 29 EINs fetched at 1 req/sec, no 429s, no robots blocks. `robots.txt` compliance confirmed.

2. **Content-addressing integrity.** Verified for Cafritz Foundation (EIN 526036989): SHA-256 of stored blob matches `RawRecord.content_sha`. Philip L. Graham Fund blob re-used from prior run — SHA matched, correct RawRecord created.

3. **Provenance chain (ProPublica path).** Traced for Cafritz Foundation: `seen` event (id=64, content_sha=1cb4ff842471...) → `funder_upserted` event (id=65, same content_sha) → materialized `Funder` row. `payload.ein == blob.org.ein == "526036989"` and `payload.canonical_name == blob.org.name == "Morris And Gwendolyn Cafritz Foundation"`. Chain complete and correct.

4. **Production seed quality.** All 29 EINs returned real organization data (0 "Organization not found" responses). This confirms the seed curation from the bug-bash was correct.

5. **EIN format.** All 29 Funders have 9-digit zero-padded EINs, no nulls, no dashes.

6. **Addresses populated.** 29/29 Funders have address in `notes`. All addresses are formatted as `{street}, {city}, {state}, {zip}`.

7. **Annual revenue populated.** 29/29 Funders have revenue history in `notes`. Years vary by org (2011–2024 range).

8. **NTEE codes.** 17/29 Funders have NTEE in notes. 12/29 have null NTEE in ProPublica — this is expected and was noted in the bug-bash candidate summary.

9. **`canonical_name_normalized` working.** Verified: "Morris And Gwendolyn Cafritz Foundation" → "morris and gwendolyn cafritz" (strips "foundation", retains "and"). Normalizer behavior confirmed per `resolution.py:normalize_funder_name`.

10. **Error guard (Bug 3 fix confirmed live).** 0 junk Funder rows. Previously 28/30 seed EINs returned "not found" and all became junk rows. This run: 0 "not found" responses and 0 junk rows.

11. **`stored_new` counter (Bug 4 fix confirmed live).** stored_new=29 for 29 unique responses — counter is now correct. Philip L. Graham Fund, whose blob was content-identical to a prior-run blob, registered `is_new=True` because the DB-level check correctly found no existing RawRecord (table was cleared). This is expected and correct behavior: `is_new` tracks DB novelty, not filesystem novelty.

12. **`snapshot_tag` command.** Created `corpus-2026-05-18-live-clean` at event_log_position=121 with non-empty manifest ref.

13. **`ingest_health` command.** Output matches actual DB state: 29 funders, 0 grants, 58 events, last_id=121. "n/a" path for resolution_rate handled correctly with 0 grants.

14. **`resolve_entities` command.** Returns cleanly with 0 rows (correct — nothing to resolve with empty HistoricalGrant table).

15. **Idempotent object store.** Pre-existing blob files are skipped on write, new RawRecords are created correctly from DB check. No file collisions or corruption.

---

## Anomalies found

### Bug 7 — `propublica_np.py:107–116` — `filings_index` always empty; IRS 990-PF run produces 0 fetches [BLOCKER]

**What:** The adapter builds a `filings_index` to tell the IRS 990-PF adapter which XML URLs to fetch:

```python
filings = [
    {"year": f.get("tax_prd_yr"), "xml_url": f.get("formtype_url") or f.get("pdf")}
    for f in data.get("filings_with_data", [])
    if f.get("formtype_url") or f.get("pdf")
]
```

Two problems:
1. `formtype_url` is `None` for all 29 orgs in the live API response. The ProPublica `filings_with_data` endpoint does not return this field.
2. The fallback `f.get("pdf")` uses the wrong key — the actual key in the API response is `pdf_url`. `f.get("pdf")` always returns `None`.

Because both lookups return `None`, the list comprehension's filter `if f.get("formtype_url") or f.get("pdf")` is always `False`, so `filings` is always `[]`, so `filings_index` is never added to `notes`.

`_build_filing_urls(--from-funders)` in `ingest_run.py:105` reads `funder.notes.get("filings_index", [])` which returns `[]` for all 29 Funders. The IRS 990-PF adapter is initialized with `filing_urls=[]`. Confirmed: `ingest_run --source irs_990pf --from-funders` produces `fetched=0`.

**Secondary complication:** Even if the field name were fixed to `pdf_url`, those URLs point to PDF files (human-readable filing PDFs). The IRS 990-PF adapter calls `ET.fromstring(body)` which will raise `ParseError` on a PDF. The adapter was designed for IRS e-file XML, not ProPublica PDF links. The correct source for 990-PF e-file XML URLs is the IRS bulk e-file index (e.g., `s3.amazonaws.com/irs-form-990/index_{YEAR}.json`), not ProPublica's `filings_with_data`.

**Where:** [grants_ingest/adapters/propublica_np.py:107-116](../grants_ingest/adapters/propublica_np.py#L107) and [management/commands/ingest_run.py:103-112](../grants_ingest/management/commands/ingest_run.py#L103)

**Severity:** Blocker. The slice-1 goal requires `HistoricalGrant` rows to be populated by the IRS 990-PF run. Currently `HistoricalGrant` count = 0.

**Suggested fix approach (for slice 2 scoping):** Replace the `filings_index`-from-ProPublica approach with direct IRS e-file index lookup. The IRS publishes annual index JSON files (`https://apps.irs.gov/pub/epostcard/form990pf/form990pf_{YEAR}.json` or the S3 bucket) keyed by EIN. For each Funder EIN, query the IRS index to get `ObjectId` values, then construct XML URLs as `https://s3.amazonaws.com/irs-form-990/{ObjectId}_public.xml`. This bypasses ProPublica entirely for the XML fetch path. The adapter code for XML parsing is sound — only the URL sourcing needs to change.

---

### Bug 8 — `_infer_funder_type` — all Funders misclassified as `public_charity` [SURGICAL / Known]

**What:** `_infer_funder_type` detects private foundations via `subsection == "92"` (IRS BMF encoding). ProPublica returns `subsection_code = 3` for ALL 501(c)(3) organizations — both public charities and private foundations. The PF/public charity distinction in ProPublica is in `foundation_code` (0 = private foundation, 15 = not a private foundation), which the adapter does not read.

Result: 28/29 Funders show `funder_type="public_charity"`, 1/29 shows "community_foundation" (correctly inferred from NTEE T3x). Known DMV private foundations — Cafritz, Bender, Philip L. Graham Fund, Pearlstone, Clark-Winchcole, etc. — are all misclassified.

**Where:** [grants_ingest/adapters/propublica_np.py:127-135](../grants_ingest/adapters/propublica_np.py#L127)

**Severity:** Surgical. Was Open Question 4 in the bug-bash handoff. No data corruption; only the classification is wrong. The IRS 990-PF run — once Bug 7 is fixed — will determine which EINs are actual 990-PF filers, providing a more authoritative signal than ProPublica's `foundation_code` anyway.

**Suggested fix:** In `_infer_funder_type`, add a `foundation_code` parameter. Add the check before the subsection check: `if foundation_code == "0": return "private_foundation"`. The adapter must also read `org.get("foundation_code")` and pass it to `_infer_funder_type`. Keep the existing `subsection == "92"` path for IRS BMF data which uses that encoding.

---

### Observation — Weissberg Foundation revenue spike [DATA QUALITY NOTE]

Weissberg Foundation (EIN 541475954, McLean VA) shows `annual_revenue: {2023: 182934492, 2022: 10540371, 2021: 3278289}` — an 18× jump from 2022 to 2023. ProPublica `totrevenue` for private foundations includes investment income and realized/unrealized gains, which can swing dramatically in a single year. This is likely a legitimate data artifact (a large endowment with a high-return year), not a wrong-org match. The Weissberg Foundation is a real DMV education-focused foundation.

**Suggested action:** None required. If `annual_revenue` is ever used as a funder-size proxy in the donor surface, add a note that year-over-year swings are expected for foundations and that multi-year averages should be used.

---

### Observation — 2 orphaned blobs in object store [INFORMATIONAL]

The object store at `/tmp/uc-corpus/raw/propublica_np/` contains 31 blob pairs (31 `.bin` + 31 `.json`). This run created 28 new files (29 fetched − 1 content-identical reuse). The prior bug-bash run left 3 blobs, 2 of which are now orphaned (no corresponding RawRecord in DB):
- `d8187aa...` — African Wildlife Foundation (EIN 520781390), not in production seed
- `4a1c649...` — the "Organization not found" error JSON from the prior bug-bash run

These cause no harm. The object store is content-addressed and orphaned blobs are inert. They will be picked up by a future corpus audit if one is ever run.

---

## Open questions for you

1. **Bug 7 fix strategy — IRS e-file index approach.** The proposed fix above replaces `filings_index`-from-ProPublica with direct IRS e-file index lookup. Confirm this is the intended approach for slice 2 before I scope the work. The IRS index files are large (one JSON per year with all e-filed 990-PFs); we would want to pre-filter by EIN rather than ingest the whole index.

2. **`foundation_code` fix timing.** Bug 8 (`funder_type` misclassification) is surgical and low-risk. Should this go into slice 1 before merge, or wait for slice 2? It's a 3-line change in `propublica_np.py` plus a test update.

3. **`RAW_OBJECT_STORE_FS_PATH` env var.** Currently there is no `.env` file and the variable must be set manually per session. The open question from the bug-bash about a dev default path (`~/Library/Application Support/uc-corpus` or a `.env.dev` template) is still unresolved. Before slice 2 adds more management commands, a `.env.dev.example` or Django settings fallback would reduce friction.

4. **HistoricalGrant provenance check deferred.** The end-to-end provenance check for HistoricalGrant (pick a grant row, trace content_sha from event log back to raw XML, verify field value) could not be performed because `fetched=0` from the IRS run. This check should be the first verification step in the next session once Bug 7 is fixed.

5. **`subsection_code` for "not a private foundation" orgs.** Several orgs in the seed have `forms={0}` in ProPublica's `filings_with_data` (Summit Fund, Greater Washington Community Foundation, Jack and Jill of America Foundation). The `formtype=0` integer is unexplained. These orgs may be 990-N filers, pre-e-file paper filers, or something else. Once the IRS index approach is in place for slice 2, these orgs may simply have no 990-PF XML to fetch, which is fine.

---

## Merge readiness

**NOT READY. One blocker.**

| Item | Status |
|---|---|
| ProPublica ingest path (fetch → store → events → Funder) | ✓ Verified |
| All 5 bug-bash fixes working against real data | ✓ Verified |
| Production seed quality (all 29 EINs resolve) | ✓ Verified |
| Provenance chain (seen → funder_upserted → Funder) | ✓ Verified |
| IRS 990-PF ingest path (fetch → store → events → HistoricalGrant) | ✗ Blocked by Bug 7 |
| HistoricalGrant provenance check | ✗ Cannot run (0 rows) |
| `resolve_entities` against real data | ✗ Not testable (0 HistoricalGrant rows) |

**Blocker:** Bug 7 — `filings_index` construction uses wrong/non-existent field names, causing the IRS 990-PF run to always produce `fetched=0` and `HistoricalGrant` count = 0. The slice-1 goal ("running `ingest_run --source irs_990pf` populates `HistoricalGrant` tables") is not met.

**Soft warnings:**
- Bug 8 (`funder_type` misclassification) — surgical fix available, low risk
- No `.env.dev` default for `RAW_OBJECT_STORE_FS_PATH` makes local dev friction higher than necessary

Fix Bug 7, re-run the IRS step, verify HistoricalGrant provenance chain, then merge.
