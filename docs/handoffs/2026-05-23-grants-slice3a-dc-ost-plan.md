# Handoff — Slice 3a Plan: DC OST Office + DC MOCA Grants Clearinghouse

**Date:** 2026-05-23
**Branch:** `feat/grants-ingest-slice2` (slice 2 not yet merged to main)
**Plan:** `docs/plans/2026-05-21-grants-ingest-slice3a-dc-ost.md`
**Session type:** Opus-tier planning only — no code written

---

## Key decisions

**opgs.dc.gov is defunct.** It redirects to ServesDC (volunteerism), not a grants portal. The "DC OPGS" entity described in the planning prompt does not have a live grants surface. Do not create a `gov_dc_opgs` adapter.

**Two adapters, not one.** `gov_dc_ost` (learn24.dc.gov) and `gov_dc_moca` (communityaffairs.dc.gov) — structurally different portals, both static HTML, no JS required. Separating them keeps each adapter legible and testable independently.

**communityaffairs.dc.gov is the real DC multi-agency grants clearinghouse.** It is the successor to what the spec called `gov_dc_opportunities` (`opportunities.dc.gov`, which is dead). The `gov_dc_moca` source ID replaces `gov_dc_opportunities` in the spec.

**Adobe Acrobat shared links are not fetchable.** The FY27 OST program-specific RFAs are currently hosted at `acrobat.adobe.com/id/urn:...` shared-document URLs. These are ephemeral and external. The `gov_dc_ost` adapter fetches only native `learn24.dc.gov/sites/default/files/*.pdf` links (supporting materials: overview, guidebook, scoring rubrics). This is a known V1 gap — the actual per-program RFA PDFs are not captured.

**Title extraction via `<title>` regex is acceptable for Tier B/C.** Extracting the page title from `<title>...</title>` with a regex is not a CSS selector or per-page layout assumption. It is used to populate `title` in the OPPORTUNITY_SEEN payload as required by the slice 3 scope ("title + funder_name_raw + source URL + raw record only").

**gov_dc_moca funder_name_raw = "DC Mayor's Office of Community Affairs" at ingest.** The issuing agency per NOFA (OSSE, DOES, DMPSJ, etc.) is deferred to Component 2 entity resolution.

---

## Open questions for Chris (need answers before implementation)

1. **Dual-funder model for gov_dc_moca**: should the adapter carry an `issuing_agency_hint` in the OPPORTUNITY_SEEN `notes` field (extracted from NOFA title via simple regex), or is one `funder_name_raw` per event correct?
2. **gov_dc_moca keyword pre-filter**: store all ~22 NOFAs as raw records (recommended) or add a configurable title deny list to skip obviously irrelevant ones at ingest?
3. **gov_dc_dpr scope**: should DC Parks and Recreation be a separate slice 3 adapter, or deferred to a later phase?
4. **Adobe Acrobat gap**: acceptable for V1, or should we attempt to fetch Acrobat shared links despite their ephemerality?
5. **gov_dc_ost OPPORTUNITY_SEEN granularity**: one event per index page (recommended, simpler) or one per discovered program (requires `<h2>` parsing, closer to CSS-selector territory)?

---

## Spec corrections to make before or during implementation

- Remove/annotate `gov_dc_opportunities` in section 5 — domain dead
- Remove/annotate CYITC from the DC agency list — defunct since 2017; OST Office supersedes
- Note that `opgs.dc.gov` is not a grants portal
- Add `gov_dc_ost` and `gov_dc_moca` rows to the source register table

---

## Recommended next action

1. Chris reviews open questions 1–5 above, answers in this thread or in a brief note at the top of the plan doc.
2. Start a new Sonnet implementation session against the plan. Paste the plan path as initial context.
3. Commit order: gov_dc_ost adapter → gov_dc_ost tests → gov_dc_moca adapter → gov_dc_moca tests → wire into ingest_run → spec update. Estimated 5–6 commits, one session.
4. After implementation, run `python manage.py ingest_run --source gov_dc_ost` and `ingest_run --source gov_dc_moca` against live URLs and report results in a live-verification handoff.

---

## Branch state

Slice 2 (`feat/grants-ingest-slice2`) is not yet merged. Slice 3a plan is committed to this same branch. The Sonnet implementation session for slice 3a can continue on this branch or branch off a new `feat/grants-ingest-slice3a` once slice 2 merges — either is fine.
