# Bug-bash — grants_ingest slice 1 live verification

**Date:** 2026-05-18 / 2026-05-19
**Branch:** `feat/grants-ingest-slice1`
**Model:** claude-sonnet-4.6
**Scope:** Live API run against ProPublica Nonprofit Explorer + IRS 990-PF, no code changes

---

## Run summary

| Step | Command | Result |
|---|---|---|
| propublica_np ingest | `ingest_run --source propublica_np` | fetched=30, stored_new=30*, parse_errors=0** |
| irs_990pf ingest | `ingest_run --source irs_990pf --from-funders` | fetched=0 |
| entity resolution | `resolve_entities` | Resolved: 0, Missed: 0 |
| snapshot | `snapshot_tag corpus-2026-05-18-live-1` | event_log_position=59, manifest=374ef9e11bd2 |
| health check | `ingest_health` | funders=2, grants=0, events=59, last_id=59 |

*stored_new=30 is incorrect — counter bug inflates it (see Bug 4).
**parse_errors=0 is incorrect — counter never increments (see Bug 5). Actual parse errors: 1.

**Actual distinct blobs stored:** 3 (2 valid org JSON, 1 error JSON shared by 28 not-found orgs)
**Funder rows produced:** 2 (1 valid with EIN, 1 junk no-EIN row)
**HistoricalGrant rows produced:** 0
**Object store root used:** `/tmp/uc-corpus` (default `/var/lib/uc-corpus` does not exist; requires sudo to create — see Open Questions)

---

## Verified working

- **Content-addressing integrity:** SHA-256 of stored blob matches `RawRecord.content_sha`. Verified end-to-end for EIN 520781390. ✓
- **Provenance chain:** `seen` event → `funder_upserted` event both linked by `content_sha`. Chain is correct for the one org whose parse() completed. ✓
- **Sidecar file:** `get_sidecar()` returns correct dict with `source_id`, `fetch_url`, `http_status`. ✓
- **Append-only enforcement:** `RawRecord` and `CorpusEvent` raise on update — not directly tested in this session but confirmed by prior unit tests.
- **Rate limiting:** No 429 responses; run took ~30s for 30 orgs at 1 req/sec. ✓
- **Robots.txt compliance:** `projects.propublica.org/robots.txt` fetched and cached; no URLs blocked. ✓
- **Idempotent store:** All 28 "Organization not found" responses hash to the same SHA; only 1 RawRecord written. ✓
- **`snapshot_tag` command:** Wrote `CorpusSnapshot` row with correct `event_log_position` and non-empty `manifest_ref`. ✓
- **`ingest_health` command:** Counts are accurate against actual DB state. Resolution rate "n/a" path handled correctly. ✓
- **`unresolved_queue` command:** Returns cleanly with zero rows. ✓
- **`materialize --since-event-id`:** Not re-run, but confirmed materialize fired correctly as part of `ingest_run`. ✓
- **Object store filesystem layout:** `raw/{source_id}/{sha[:2]}/{sha}.bin` + `.json` confirmed on disk at `/tmp/uc-corpus`. ✓

---

## Anomalies found

### Bug 1 — `propublica_np.py:71` — `ntee_code` explicit null crashes parse() [BLOCKER]

**What:** `ntee = org.get("ntee_code", "")` returns `None` when the key exists in the API response with a JSON `null` value (`.get()` default only fires on missing key, not on `null` value). `_infer_funder_type(subsection, ntee)` then calls `ntee.startswith("T3")` → `AttributeError: 'NoneType' object has no attribute 'startswith'`.

**Where:** [grants_ingest/adapters/propublica_np.py:71](../grants_ingest/adapters/propublica_np.py#L71) and [propublica_np.py:122-130](../grants_ingest/adapters/propublica_np.py#L122)

**Severity:** Blocker. Any org with `ntee_code: null` in the ProPublica response causes parse() to throw, which prevents the `funder_upserted` event from being logged and the org from being materialized. The Graham Fund (526051781) — a real DMV private foundation — was lost due to this bug.

**Evidence:** `'NoneType' object has no attribute 'startswith'` error in ingest_run stderr for EIN 526051781. Graham Fund has `ntee_code: null` in API response; AWF has `ntee_code: 'D30Z'` (string) and parsed fine.

**Proposed fix (surgical, single line):**
```python
# line 71: change
ntee = org.get("ntee_code", "")
# to
ntee = org.get("ntee_code") or ""
```

---

### Bug 2 — `propublica_np.py:73` — wrong field name `subseccd` vs `subsection_code` [BLOCKER]

**What:** `subsection = str(org.get("subseccd", ""))` — the adapter looks for `"subseccd"` but the ProPublica API returns `"subsection_code"`. The field is always missing under the expected name, so `subsection` is always `""`, so `_infer_funder_type` never sees the right value, and every org gets `funder_type="unknown"`.

**Where:** [grants_ingest/adapters/propublica_np.py:73](../grants_ingest/adapters/propublica_np.py#L73)

**Severity:** Blocker for funder classification. All Funders stored with `funder_type="unknown"`. Private foundations (subsection_code=92) cannot be distinguished from public charities. The IRS 990-PF adapter will eventually need this for scoping which orgs to fetch XML for.

**Evidence:** Both orgs fetched have `subsection_code=3` in the response. `Funder.objects.values('funder_type').annotate(n=Count('id'))` shows 100% "unknown".

**Proposed fix (surgical, single line):**
```python
# line 73: change
subsection = str(org.get("subseccd", ""))
# to
subsection = str(org.get("subsection_code") or org.get("subseccd") or "")
```
Note: keep the `subseccd` fallback — IRS BMF bulk data uses the older name.

---

### Bug 3 — `propublica_np.py:66` — error API response treated as valid org data [BLOCKER]

**What:** `org = data.get("organization") or data` — when the ProPublica API returns `{"data_source": "...", "api_version": "...", "error": "Organization not found"}` (no `organization` key), `data.get("organization")` is `None` (falsy) and `org` falls back to the full error dict. The adapter proceeds to extract `ein`, `name`, etc. from it, finds nothing, and emits a `funder_upserted` event with `ein=None, name=""`.

**Where:** [grants_ingest/adapters/propublica_np.py:66](../grants_ingest/adapters/propublica_np.py#L66)

**Severity:** Blocker. 28 of 30 seed EINs returned "Organization not found". Each emitted a blank `funder_upserted` event, all 28 of which collapsed onto a single junk `Funder` row (no EIN, no name) in the materializer. Event log now contains 28 meaningless events. A re-run would produce 28 more.

**Evidence:** 28 `funder_upserted` events with `ein=None, name=""`. DB has a `Funder` row with `ein=None, canonical_name=""`. Error blob has identical content for all 28 — one stored RawRecord, but 28 CorpusEvent rows pointing at it.

**Proposed fix (surgical, 3 lines):**
```python
# After line 66, before extracting fields:
org = data.get("organization")
if not org:
    logger.warning("propublica_np: no organization data for %s", raw.content_sha)
    return []
```
This makes missing org a silent skip (no parse_failed event, no junk upsert). Optionally return `PARSE_FAILED` if you want error visibility in the event log.

---

### Bug 4 — `base.py:108-111` — `stored_new` counter always equals `fetched` [SURGICAL]

**What:** The `stored_new` counter check is logically broken:
```python
if (
    not RawRecord.objects.filter(content_sha=raw.content_sha)
    .exclude(pk=raw.pk)
    .exists()
):
    result.stored_new += 1
```
Since `content_sha` is the primary key, `exclude(pk=raw.pk)` always removes the only matching record, making `.exists()` always `False`, making `not False` always `True`, and `stored_new` always increments regardless of whether the blob was actually new.

**Where:** [grants_ingest/adapters/base.py:108-111](../grants_ingest/adapters/base.py#L108)

**Severity:** Surgical. No data corruption — only the operator-facing counter is wrong. `stored_new=30` was reported for a run that stored 2 new blobs and re-used 1 existing (the error blob counted 28 times). Breaks idempotency monitoring: re-running will show `stored_new=30` again instead of `0`.

**Evidence:** 30 seed EINs, 3 distinct RawRecords stored, but `stored_new=30`.

**Proposed fix:** Pass `is_new` from `fetch_one()` back through the return value (e.g., return a tuple `(raw, is_new)`) and use it in `run()`. Alternatively, check `is_new` before the `result.fetched += 1` block and pass it forward.

---

### Bug 5 — `base.py` — `parse_errors` counter never incremented [SURGICAL]

**What:** `AdapterRunResult.parse_errors: int = 0` is defined but never set anywhere in `run()`. Exceptions from `parse()` fall into the broad `except Exception as exc` block, which appends to `result.errors` but does not increment `parse_errors`. All parse failures are invisible in the summary line.

**Where:** [grants_ingest/adapters/base.py:100-123](../grants_ingest/adapters/base.py#L100) and [adapters/types.py](../grants_ingest/adapters/types.py)

**Severity:** Surgical. Operationally misleading: `parse_errors=0` printed even when parse failed for 1 org. Also, the error log message says `"Error fetching %s"` for what is actually a parse error — confusing attribution.

**Proposed fix:** Track whether the exception came from `fetch_one()` vs `parse()` by restructuring the try/except:
```python
try:
    raw = self.fetch_one(task, client)
    result.fetched += 1
except ...:
    ...

try:
    events = self.parse(raw)
    ...
except Exception as exc:
    logger.error("Error parsing %s: %s", task.url, exc)
    result.parse_errors += 1
    result.errors.append(str(exc))
```

---

### Bug 6 — Seed list — 28/30 EINs invalid in ProPublica [DATA QUALITY, not code]

**What:** 28 of 30 EINs in `grants_ingest/seeds/dmv_foundations.yml` returned "Organization not found" from the ProPublica Nonprofit Explorer API. The 2 that resolved belong to wrong organizations:
- EIN `520781390` → **African Wildlife Foundation** (seed claims: Eugene and Agnes E. Meyer Foundation)
- EIN `526051781` → **Philip L. Graham Fund** (seed claims: Morris and Gwendolyn Cafritz Foundation)

The seed list was AI-generated from training-data recall. EINs were not verified against ProPublica or IRS BMF at generation time.

**Where:** [grants_ingest/seeds/dmv_foundations.yml](../grants_ingest/seeds/dmv_foundations.yml)

**Severity:** Data quality blocker for the intended use case. AWF (animal welfare public charity) has no 990-PF filings. The IRS 990-PF run produced `fetched=0` as a direct consequence: no valid private-foundation Funders in the DB to look up filing URLs for.

**Fix required:** Manual EIN lookup for each entry. Recommended approach:
1. Search ProPublica Nonprofit Explorer by *name* for each org in the seed list
2. Copy the EIN from the matching result
3. Cross-reference against the IRS BMF nonprofit search at apps.irs.gov/app/eos/
4. Do not re-run the ingest until the seed list is corrected — current EINs will pollute the event log

---

## Open questions for you

1. **Object store default path `/var/lib/uc-corpus` requires sudo to create on macOS.** Should the default be `~/Library/Application Support/uc-corpus` on macOS, or should there be a `RAW_OBJECT_STORE_FS_PATH` env var set in a `.env.dev` template? Currently there is no `.env` file at all; local runs require the env var to be set manually.

2. **Junk Funder row in the DB.** There is now a `Funder` row with `ein=None, canonical_name=""` from the 28 error events. After Bugs 1–3 are fixed and the seed list is corrected, should I wipe the DB and run fresh, or is there a migration / data-fix path you want? (Recommend: wipe and re-run from clean state.)

3. **28 junk CorpusEvents.** Same question — 28 `funder_upserted` events with empty payloads are in the log. These can't be deleted (append-only). They're harmless but noisy. One option: accept as a known bad data artifact of the first live run; document in the dev log.

4. **ProPublica `subsection_code` for private foundations.** The field is `3` (501c3) for public charities and appears to also be `3` for private foundations on ProPublica — the PF/public charity distinction is encoded in `foundation_code`, not `subsection_code`. Value `15` = "Not a private foundation"; value `0` = "Organization is a private foundation". Should `_infer_funder_type` look at `foundation_code` instead of (or in addition to) `subsection_code`?

---

## Recommended next action

**Surgical fixes required before merge.** The three code bugs (1, 2, 3) collectively produce zero usable output from the DMV seed list. The two counter bugs (4, 5) are misleading but don't corrupt data. The seed list is a separate data-curation task.

Recommended sequence:
1. Apply surgical fixes for Bugs 1, 2, 3 in a single commit (they're all in `propublica_np.py`, ~5 lines total).
2. Apply Bug 4 + Bug 5 fixes in a second commit (`base.py`).
3. Manually curate the seed list EINs (human task — verify against ProPublica by name search).
4. Wipe the dev DB, re-run the full ingest sequence, re-run this bug-bash checklist.
5. If clean: merge.

Do not merge as-is. The pipeline is architecturally sound but produces no valid output against real data in its current state.
