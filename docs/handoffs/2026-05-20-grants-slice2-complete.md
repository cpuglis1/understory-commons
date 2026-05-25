# Grants Ingest Slice 2 — Handoff

**Date:** 2026-05-20
**Branch:** `feat/grants-ingest-slice2`
**Plan:** `docs/plans/2026-05-19-grants-ingest-slice2-tierA.md`

---

## What shipped

### New adapters

**`GrantsGovAdapter`** (`grants_ingest/adapters/grants_gov.py`)
- Fetches the daily grants.gov XML bulk extract (one zip, all open opportunities)
- Unzips and iterparses XML in-memory (bounded memory, `elem.clear()` after each record)
- Three pre-filter rules at parse time:
  - Rule 1: EligibleApplicants must include code 25 (nonprofits) or 12 (other nonprofit)
  - Rule 2: CFDA prefix in (84., 93.5, 16.) OR CategoryOfFundingActivity in {E, ED, HL}
  - Rule 3: AwardFloor absent or < $250,000
- Passing → `OPPORTUNITY_SEEN`; failing → `OPPORTUNITY_FILTERED` with reason code
- Second-pass PDF fetch: if `Description` is a bare `.pdf` URL, fetches it as a separate `RawRecord` (50 MB cap via HEAD, stored content-addressed, M2M-linked via `extra_content_shas`)
- 29 tests, all passing

**`PNDRfpAdapter`** (`grants_ingest/adapters/pnd_rfp.py`)
- Two-pass run: Pass 1 fetches RSS and geo-filters; Pass 2 fetches funder source pages
- Geographic pre-filter: national/DC/MD/VA/DMV pass; state-specific outside that region fails
- Within-run GUID dedup; cross-run GUID dedup with `OPPORTUNITY_UPDATED` on deadline change
- HTML named entity sanitizer (`_sanitize_rss_xml`) pre-processes RSS before ElementTree
- Source pages stored as second `RawRecord`, M2M-linked via `extra_content_shas`
- 15 tests, all passing

### Infrastructure changes

- **`CorpusEventType`**: added `OPPORTUNITY_SEEN`, `OPPORTUNITY_UPDATED`, `OPPORTUNITY_FILTERED`
- **`OpportunityInstance`** model: added `notes`, `source_id`, `external_id`, `funder_name_raw`; `unique_together = [("source_id", "external_id")]`
- **Migration `0007`**: the four new fields + unique_together + updated event_type choices
- **Materializer** (`apply_events`): handles `OPPORTUNITY_SEEN` (upsert + M2M), `OPPORTUNITY_UPDATED` (field updates), `RESOLVED` for opportunities
- **`ingest_run`**: `--source` now accepts `pnd_rfp` and `grants_gov` (4 choices total); dispatch refactored to `_build_adapter()` factory
- **`resolve_entities`**: `--target opportunities|historical_grants|all`; grants_gov misses auto-create stub `Funder` rows (Q2 asymmetric decision); pnd_rfp misses remain unlinked
- **`ingest_health`**: adds total/unlinked opportunity counts + per-source breakdown
- **`BaseAdapter`**: `_DEFAULT_HEADERS` with browser User-Agent applied to all httpx clients
- **Settings**: `RAW_OBJECT_STORE_FS_PATH` defaults to `/tmp/uc-corpus`; `.env.dev.example` added

---

## Live verification results

### grants_gov
- HTTP 404: S3 bucket `prod-grants-gov-chamel` does not exist
- The URL pattern `https://prod-grants-gov-chamel.s3.amazonaws.com/extracts/GrantsDBExtract{date}v2.zip` needs to be verified against the current grants.gov data feed documentation
- **Action required before first production run**: confirm correct S3 bucket name and URL format from [GrantData.gov](https://grantsdata.gov/) or the grants.gov developer portal

### pnd_rfp
- `philanthropynewsdigest.org/rfps/rss` now redirects to the Candid homepage (`candid.org`)
- PND was absorbed into Candid (Foundation Center + GuideStar merger); the RFP feed may have moved to a Candid URL or may require a Candid account
- **Action required**: verify the current Candid/PND RSS feed URL or confirm the source is discontinued
- Adapter logic, parsing, entity sanitization, and geo-filter are correct; only the URL needs updating

### All 127 adapter/materializer tests passing

---

## Known limitations carried forward

1. **grants_gov URL**: needs bucket name verification (live URL unknown at time of shipping)
2. **pnd_rfp URL**: PND has moved to Candid; correct RSS URL unknown
3. **CFDA field mapping**: the grants.gov XML uses `<CFDANumbers>` but the actual format in production may differ (validated against synthetic fixtures only)
4. **OpportunityInstance.funder linkage**: `resolve_entities --target opportunities` populates `funder_id` for grants_gov; initial run will auto-create many stub Funders; plan a review pass to merge/clean stubs before donor surface uses them

---

## Deferred (slice 3)

- Playwright-based scraping sources
- LLM extraction pass on stored raw HTML/PDF
- Donor-surface OpportunityInstance views
- Railway cron wiring for daily runs
- PDF content cap enforcement in `_fetch_pdf` (currently relies on HEAD; a server that omits Content-Length will download uncapped until the content is stored — add streaming chunk check)

---

## Next steps

1. Verify grants.gov S3 URL against current documentation; update `_EXTRACT_URL_TPL` in `grants_gov.py`
2. Verify Candid/PND RSS URL; update `DEFAULT_RSS_URL` in `pnd_rfp.py`
3. Run `ingest_run --source grants_gov` against live URL once confirmed
4. Run `resolve_entities --target opportunities` to populate funder links
5. Run `ingest_health` to validate counts
6. Merge `feat/grants-ingest-slice2` → `main`
