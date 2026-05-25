# Handoff — Structured Field Extraction (Slice 3b)

**Date:** 2026-05-24
**Branch:** `feat/grants-ingest-structured-fields` (off `feat/grants-ingest-slice2`)
**Snapshot:** `corpus-2026-05-24-structured-fields-backfilled` (event_log_position=329748)
**Tests:** 213 passed (169 prior + 44 new extractor tests)

---

## What shipped

| Commit | Description |
|--------|-------------|
| `7fe0401` | `feat(grants_ingest): structured field extraction module + tests` |
| `06b39f2` | `feat(grants_ingest): wire structured extractors into all 5 DC adapters` |
| `298aa22` | `feat(grants_ingest): materializer handles status, eligibility, subject_areas, funder_name_raw` |
| `bcafb45` | `feat(grants_ingest): backfill_structured_fields management command` |

---

## Field coverage after backfill (56 DC rows total)

| Source | close_at | award_min | award_max | subject_areas | org_type |
|--------|:--------:|:---------:|:---------:|:-------------:|:--------:|
| gov_dc_ost (2) | 2/2 | 0/2 | 0/2 | 2/2 | 1/2 |
| gov_dc_moca (38) | 0/38 | 0/38 | 0/38 | 38/38 | 0/38 |
| gov_dc_cah (14) | 3/14 | 0/14 | 1/14 | 14/14 | 2/14 |
| dc_humanitiesdc (1) | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| dc_eventsdc (1) | 1/1 | 0/1 | 0/1 | 1/1 | 1/1 |
| **Total** | **7/56 (12%)** | **1/56 (2%)** | **2/56 (4%)** | **56/56 (100%)** | **5/56 (9%)** |

**Key win:** `subject_areas` is 100% populated. All DC rows are now filterable by topic.

**Award amounts — honest assessment:** DC government portal HTML pages (OST, MOCA, CAH) don't publish individual award ceilings in their index/detail page text — those numbers live in the RFA PDFs. The range extractor works correctly when award text is present (HumanitiesDC: $8K–$13K extracted correctly). Award amount extraction from PDFs is Component 2's job, not ingest.

---

## MOCA agency attribution

| Pass | Attributed | Fallback | Attribution rate |
|------|:----------:|:--------:|:----------------:|
| Before (title-level only) | 3/38 | 35/38 | 8% |
| After (title + body-level) | 4/38 | 34/38 | 10.5% |

Body-level search found 1 additional attribution (marginal lift). MOCA NOFAs name programs (not agencies) in their titles AND in their body text. The 34 unattributed rows describe specific programs (NEVI, Immunization Coalition, etc.) with no agency abbreviation or full name visible in the HTML. The agency relationship is in the PDF attachment. Deferring to Component 2.

---

## find_grants before/after

| Profile | Before backfill | After backfill | Delta |
|---------|:---------------:|:--------------:|:-----:|
| `dmv_youth_ed_sample.yaml` (no limit) | 347 | 347 | 0 |

DC rows still don't appear in `dmv_youth_ed_sample.yaml` results because the profile requires `award_min_gte: 10000` and only 1 DC row has `award_min` set ($8K, below the threshold). The `subject_areas` filter (education, E, ED) DOES match OST and MOCA/OSSE rows, but `award_min_gte` overrides.

**What changed:** DC rows are now fully filterable by `subject_areas` and partially filterable by `application_close_at` and `status`. A profile without `award_min_gte` (or with `award_min_gte: 0`) will now return the relevant DC rows. Suggested profile update for demo use:

```yaml
filters:
  open_only: true
  subject_areas:
    - education
    - youth_development
    - arts
    - humanities
```

This profile (without `award_min_gte`) returns DC rows with matching subject areas.

---

## Known anomalies

- **OST: award_max = null (corrected from prior run that showed $22.1M).** The "Funding Opportunities" index page contained "In total, up to $22.1 million" referring to total program budget across all OST providers. The extractor now correctly excludes total-pool context from `award_max` extraction (prefix check for "total", "pool", "program", etc.).

- **OST close_at = "closed"**: Both OST rows have past close dates (2026-04-28 and 2023-05-17). This is correct — the OST FY27 RFAs are closed; the index page describes the program. Status = "closed" is accurate.

- **MOCA dates = null**: MOCA publication pages are announcement text without explicit deadlines in the HTML body. Deadlines are in the attached PDF NOFAs. Component 2.

- **Spec update needed**: The Principle 4 language in `grant_ingestion.md` ("Tier B/C is not parsed at ingest") is now outdated. The updated principle is: deterministic fields are extracted at ingest using rule-based extractors; semantic extraction (eligibility prose, mission alignment, amount-from-PDF) remains Component 2's responsibility. The spec has not been updated yet — do that in the next session.

---

## Architecture decisions recorded here

- `grants_ingest/extraction/` package now owns all deterministic extraction logic. Adapters call `build_structured_fields()` from `dc_html_util.py` rather than importing extractors directly (centralises the "call extractors, build payload" logic).
- Materializer `_apply_opportunity_seen` now gates `subject_areas` and `geographic_scope` with `if payload.get()` — consistent with existing `title`, `funder_name_raw`, `notes` gates. Prevents attachment-link events from overwriting populated fields.
- `backfill_structured_fields` materializes only events emitted in the current run (not the full event log replay), making it feasible against a 300K+ event log.

---

## What's next

1. **Merge** `feat/grants-ingest-slice2` → main (includes slice 2, slice 3a, and this slice 3b).
2. **Update** `grant_ingestion.md` Principle 4 to reflect the refined Tier B/C extraction policy.
3. **Update** `CLAUDE.md` Current phase to the next slice.
4. **Sample profile update** for DC-demo use (see profile suggestion above).
5. **Component 2** (PDF extraction for award amounts, MOCA agency from PDF body) — next big lift.
