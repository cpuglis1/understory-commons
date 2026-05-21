# IRS 990PF Adapter — Batch-Zip Rewrite Handoff

**Date:** 2026-05-21
**Branch:** `feat/grants-ingest-slice2`
**Commit:** `feat(grants_ingest): irs_990pf batch-zip rewrite (AWS bucket decommissioned)`

---

## Why this rewrite happened

AWS decommissioned the IRS 990 Registry-of-Open-Data S3 bucket. Every
per-filing URL of the form
`https://s3.amazonaws.com/irs-form-990/{object_id}_public.xml`
now returns HTTP 404. Verified live 2026-05-21 against multiple known-good
object IDs from the ProPublica filings index.

The replacement source is the IRS ePostcard site's monthly batch zips, which
have been stable and are the current IRS-endorsed bulk download path.

---

## What shipped

### `grants_ingest/adapters/irs_990pf.py` — v0.2.0

**Changed:**
- `__init__` now takes `seed_eins: list[str]` and `months_back: int = 3`;
  the old `filing_urls: list[dict]` parameter is gone.
- `iter_fetch_tasks()` yields monthly zip URLs (current month going back
  `months_back` steps, all three letter variants A/B/C). URL pattern:
  `https://apps.irs.gov/pub/epostcard/990/xml/{YYYY}/{YYYY}_TEOS_XML_{MM}{LETTER}.zip`
- `run()` overridden: downloads each zip into `BytesIO`, opens with
  `zipfile.ZipFile`, iterates entries, applies two-stage filter, stores
  matching entries as content-addressed `RawRecord` rows, calls `parse()`.
- `_process_zip()` and `_process_entry()` are new private methods.
- `_should_process()` new module-level helper: parses `ReturnTypeCd` and
  `Filer/EIN`; returns `(should_keep, ein)`.
- HTTP 302 and 404 responses are silently skipped (not-yet-posted months).
- Rate limit (1 req/sec) applies to zip downloads, not per-entry parsing.

**Unchanged:**
- `_NS`, `_find_text`, `_find_filer_ein`, `_find_tax_year`
- `_extract_part_xv1`, `_find_recipient_name`, `_find_recipient_ein`,
  `_find_recipient_address`
- `_extract_part_xv2`
- `parse()` method body — reads a single stored XML, emits
  `HISTORICAL_GRANT_RECORDED` and `FUNDER_ENRICHED` events unchanged.

### `grants_ingest/management/commands/ingest_run.py`

**Removed flags:** `--from-funders`, `--from-seed-list`, `--all-filings`
**Added flag:** `--months-back` (int, default 3)
**Deleted:** `_build_filing_urls()` function (built per-filing URLs from the
ProPublica filings index stored in `Funder.notes`; no longer needed).

The `irs_990pf` adapter branch now:
```python
eins = _load_eins(options["seed_list"])
return IRS990PFAdapter(store=store, event_log=event_log,
                       seed_eins=eins, months_back=options["months_back"])
```

### `tests/grants_ingest/fixtures/irs_990pf_monthly_sample.zip`

New synthetic binary fixture. Contains 3 XML entries:
- `matching_990pf.xml` — 990PF, EIN `990000099` (seed EIN); has one Part
  XV-1 grant row.
- `nonmatching_990pf.xml` — 990PF, EIN `990000088` (not in seed); must be
  dropped.
- `matching_990_wrongtype.xml` — form type `990` (not `990PF`), EIN
  `990000099`; must be dropped.

### `tests/grants_ingest/test_irs_990pf_adapter.py`

Rewritten. 17 test cases covering:
- `_should_process` filter logic for all three decision paths + malformed XML
- `_process_zip` store/no-store decisions (3 entries → 1 stored)
- Idempotency (same zip twice → same 1 record)
- Grant event emission from zip path
- `parse()` regression parity using the old `irs_990pf_synthetic.xml` fixture
- `iter_fetch_tasks` URL count, format, and year-boundary wrapping

All 132 grants_ingest tests pass.

### `docs/plans/2026-05-18-grants-ingest-funder-registry.md`

Section 11 appended: "URL Pattern Revision (2026-05-21)" documenting the AWS
decommission, new URL pattern, and implementation summary.

---

## Known limitations / deferred

1. **`Funder.notes['filings_index']`** populated by ProPublica is now
   informational only — the IRS adapter no longer reads it to find XML URLs.
   The field can be kept as provenance metadata; no schema change needed.

2. **ProPublica `filings_index` XML URLs** are still served (ProPublica
   mirrors the 990 XML files). If a targeted single-filing lookup is ever
   needed, the per-URL path could be restored as an opt-in mode. Not needed
   for V1.

3. **Current-month zip** (e.g. `2026_TEOS_XML_05A.zip`) returns HTTP 302.
   The adapter skips it silently. First-of-month runs will have one fewer
   month of data until IRS posts the zip (typically ~2 weeks lag).

4. **360-second fetch timeout** is set on the httpx client. On a very slow
   connection a 260 MB zip could exceed this. Increase `timeout` in
   `IRS990PFAdapter.run()` if prod runs time out.

5. **Memory**: each zip is buffered entirely in RAM as `BytesIO` (150–260 MB).
   This mirrors the `grants_gov` adapter pattern and is acceptable for a
   single-process Railway worker. If OOM becomes an issue, switch to streaming
   extraction (Python's `zipfile` supports `open()` on individual entries
   without full decompression).

---

## Next steps

1. Run `python manage.py ingest_run --source irs_990pf --months-back 1`
   against the live IRS endpoint to populate at least one `HistoricalGrant`
   row for a DMV-region foundation. Verify with
   `python manage.py ingest_health`.
2. Run `python manage.py resolve_entities --target historical_grants` to
   link grant rows to `Funder` records.
3. Verify grants.gov S3 URL (see slice-2 handoff — still needs the correct
   bucket name).
4. Merge `feat/grants-ingest-slice2` → `main` once grants_gov URL is
   confirmed and at least one live end-to-end run passes.
