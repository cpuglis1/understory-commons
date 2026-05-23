# Handoff — Slice 3a Plan: Five DC Sources (Complete)

**Date:** 2026-05-23
**Branch:** `feat/grants-ingest-slice2` (slice 2 not yet merged to main)
**Plan:** `docs/plans/2026-05-23-grants-ingest-slice3a-dc.md`
**Supersedes:** `docs/handoffs/2026-05-23-grants-slice3a-dc-ost-plan.md` (OST + MOCA only)
**Session type:** Opus-tier planning only — no code written

---

## What this plan covers

Five DC grant sources, all verified live 2026-05-23:

| Source ID | URL | Status |
|-----------|-----|--------|
| `gov_dc_ost` | learn24.dc.gov | Carried forward from prior plan; all decisions validated |
| `gov_dc_moca` | communityaffairs.dc.gov | Carried forward; funder policy changed (see below) |
| `gov_dc_cah` | dcarts.dc.gov | New in this plan |
| `dc_humanitiesdc` | humanitiesdc.org | New in this plan |
| `dc_eventsdc` | eventsdc.com | New in this plan |

---

## Key decisions

**Naming: `dc_*` prefix for HumanitiesDC and Events DC.** Not `gov_dc_*`. The `gov_dc_*` namespace is reserved for DC executive-branch agencies. HumanitiesDC is a federally chartered 501(c)(3); Events DC is a DC instrumentality (WCSA) but not an executive agency. `dc_humanitiesdc` and `dc_eventsdc` are accurate and create a clean namespace for non-agency DC funders.

**gov_dc_moca funder policy change from prior plan.** The prior plan set `funder_name_raw = "DC Mayor's Office of Community Affairs"` for all MOCA NOFAs. This plan changes the policy to extract the issuing agency from the NOFA title using a DC agency abbreviation regex (`DC_AGENCY_NAMES` dict in `dc_html_util.py`). Each NOFA's issuing agency becomes its own `funder_name_raw`. If no agency is found in the title, fall back to `"DC Government (agency unresolved)"`. This is Q1 — needs Chris's sign-off.

**Shared utility module: `grants_ingest/adapters/dc_html_util.py`.** Consolidates `extract_title`, `scan_hrefs`, `DC_AGENCY_NAMES`, `extract_moca_agency`, and `fetch_pdf` into one place. All five adapters import from here rather than duplicating.

**Two Sonnet sessions, 3+2 split.** Session 1: `gov_dc_ost + gov_dc_moca` (more complex, three-pass MOCA). Session 2: `gov_dc_cah + dc_humanitiesdc + dc_eventsdc` (simpler, two-pass and one-pass adapters). Session 1 establishes the shared utilities; Session 2 builds on them.

**gov_dc_cah has no PDFs currently.** The RFA PDFs for FY2027 are described as "scheduled for spring/summer 2026" — not yet posted. The adapter scans detail pages for PDF links and fetches them when present. Adapter is correct at time of survey; PDFs will appear on existing detail pages when posted.

**dc_eventsdc funder_type = govt_local.** No `quasi_govt` enum value exists in the Funder schema. Using `govt_local` with `notes['quasi_public'] = True` as a flag. If `quasi_govt` is added to the schema later (requires migration + Opus review), Events DC should be migrated.

**Dead sources to retire from spec:** `gov_dc_opportunities` (dead), `gov_dc_opgs` (redirects to ServesDC), CYITC (defunct since 2017). All three removed from section 5 in commit 13.

---

## Open questions for Chris (need sign-off before Session 1)

1. **MOCA funder extraction:** Approve the `extract_moca_agency()` regex approach, or fall back to single `funder_name_raw = "DC Mayor's Office of Community Affairs"` for all MOCA events?
2. **HumanitiesDC granularity:** One OPPORTUNITY_SEEN per index page (recommended) or one per program heading?
3. **Events DC funder_type:** Accept `govt_local` for Events DC, or add `quasi_govt` to the enum (migration)?
4. **CAH program scope:** Fetch all 15–17 detail pages, or pre-filter to competitive-grants-only?
5. **dc_humanitiesdc apply_url:** Capture GrantInterface URL explicitly in OPPORTUNITY_SEEN payload, or leave in raw bytes only?
6. **Adobe Acrobat gap:** Explicit sign-off that not fetching FY27 OST RFA PDFs is acceptable for V1.

---

## Recommended next action

1. Chris reviews open questions 1–6; answers inline or in a note.
2. Start Sonnet Session 1 with:
   - `docs/plans/2026-05-23-grants-ingest-slice3a-dc.md` as initial context
   - Focus: `dc_html_util.py`, `gov_dc_ost`, `gov_dc_moca` (commits 1–6)
3. After Session 1: live-verify both adapters (`ingest_run --source gov_dc_ost`, `ingest_run --source gov_dc_moca`), write a brief verification note.
4. Start Sonnet Session 2 with the same plan, focus on commits 7–13.
5. After both sessions: run `resolve_entities`, `ingest_health`, verify all 5 sources show up in `find_grants` output.

---

## Branch state

Slice 2 (`feat/grants-ingest-slice2`) is not yet merged to main. The OST+MOCA plan (commit 4b98f53) and this plan are on the same branch. Implementation sessions for slice 3a should continue on this branch or branch off `feat/grants-ingest-slice3a` once slice 2 merges — either is fine.
