# Handoff — Slice 3a Complete (5 DC Sources Live)

**Date:** 2026-05-23
**Branch:** `feat/grants-ingest-slice2` (slice 2 + slice 3a co-located; not yet merged)
**Plan:** `docs/plans/2026-05-23-grants-ingest-slice3a-dc.md`
**Session type:** Sonnet implementation, Session 2 of 2
**Snapshot:** `corpus-2026-05-23-slice3a-complete` (event_log_position=329578)

---

## What shipped this session

| Commit | Description |
|--------|-------------|
| `daa88d4` | `feat(grants_ingest): gov_dc_cah adapter — index + detail pages + PDF scan` |
| `4e77483` | `feat(grants_ingest): dc_humanitiesdc adapter — index + native PDF fetch` (+ materializer notes-overwrite fix) |
| `89ac8fc` | `feat(grants_ingest): dc_eventsdc adapter — index + PDF fetch` |
| `1f86d68` | `feat(grants_ingest): wire 3 DC adapters into ingest_run + spec update` |

All five slice-3a DC adapters are live, materialized, and snapshotted.

---

## Phase A — Session 1 verification findings

### 1. gov_dc_ost = 2 OpportunityInstance — by design, not a bug

Investigation result: the "7 FY27 RFAs → 2 rows" gap is the deliberate
Tier B/C behavior specified in plan §6:

> Alternatively, emit one OPPORTUNITY_SEEN per index page fetch (simpler,
> consistent with gov_dc_ost), using the page title as the title. **This
> is the V1 recommendation — one record per page fetch, not one per
> program. Component 2 will split them.**

The two rows correspond to the two index URLs (`/page/ost-office-grants` =
FY27 active, `/page/funding-opportunities-0` = archival). 36 native PDFs
(strategic plan, RFAs, scoring rubrics, annual reports) were fetched as
secondary RawRecords and M2M-linked to those two rows. 27 Acrobat
shared-document URLs were correctly skipped and logged as
`opportunity_filtered` with reason `external_link_unarchivable`.

No bug. No follow-up needed.

### 2. gov_dc_moca = 38 — multi-agency funder policy partially working

`funder_name_raw` distribution across the 38 rows:

| Count | funder_name_raw |
|------:|-----------------|
| 35 | DC Government (agency unresolved) |
| 2 | DC Office of the State Superintendent of Education |
| 1 | DC Department of Employment Services |

The good news: zero rows collapsed to "MOCA" / "DC Mayor's Office of
Community Affairs". The agency-extraction policy from plan §5 is
firing, just at very low precision — **92% of NOFAs (35/38) fall back to
"DC Government (agency unresolved)"** because most MOCA NOFA titles use
program names (e.g., "FY26 National Electric Vehicle Infrastructure
(NEVI) Program", "DC Immunization Coalition Funding NOFA") rather than
agency abbreviations. Only titles containing OSSE, DOES, DC Health, DBH,
DDOT, DMPED, etc. match.

**Follow-up for a future session (not slice 3a):** extract the issuing
agency from the publication page body (Drupal sidebar, "Posted by"
metadata, or description text) rather than from the title alone. This
would likely lift precision toward 80%+ at the cost of one regex per
publication-page parse. Document on the slice-3 backlog; not blocking
slice 3a merge.

### 3. find_grants — DMV sample profile produces zero DC matches by design

Phase A baseline: 348 rows returned, **all from grants_gov**. Zero DC
rows match `profiles/dmv_youth_ed_sample.yaml` because the profile
requires `award_min_gte: 10000` AND a `subject_areas` match. DC Tier B/C
rows have neither (by design — title + funder_name_raw + URL only). The
DC corpus is fully indexed but is not yet *filterable* by this profile.

Verified by running `find_grants --profile profiles/all.yaml --limit
100000`: 40 DC rows surfaced in Phase A (38 MOCA + 2 OST). After Phase C
ingest, 56 DC rows surface (40 + 14 CAH + 1 HumanitiesDC + 1 EventsDC).

**Implication for the "demoable" check:** the "DC corpus producing real
local matches that grants.gov alone didn't" claim from the prompt
requires either (a) Component 2 enriching DC rows with award_min and
subject_areas extracted from the linked PDFs, or (b) a different sample
profile (e.g., one without `award_min_gte` or `subject_areas` filters,
or one with `sources: [gov_dc_ost, gov_dc_moca, gov_dc_cah,
dc_humanitiesdc, dc_eventsdc]`). Both are out of scope for slice 3a.

---

## Phase B — Three adapters shipped

### gov_dc_cah (dcarts.dc.gov) — two-pass

- Pass 1: `/page/grant-programs` → discovers `/grants/{slug}` and
  `/public-art/{slug}` detail links (deduped relative+absolute,
  self-link skipped).
- Pass 2: each detail page → `OPPORTUNITY_SEEN` with hardcoded funder
  "DC Commission on the Arts and Humanities" + scan for
  `/sites/default/files/*.pdf` (none present at survey time; adapter
  picks them up automatically when posted).
- One Lincoln Theatre Rental entry on the live page uses a
  `/publication/...` URL — that pattern is **not** matched by the
  current regex. Lincoln Theatre is informational rental support, not
  an open RFP — acceptable scope per plan §1.3 which defines URL
  patterns as `/grants/` and `/public-art/` only.
- Tests: 5/5 passing.

### dc_humanitiesdc (humanitiesdc.org) — two-pass

- Pass 1: `/grant-opportunities` → one `OPPORTUNITY_SEEN` for the whole
  index (Q2 V1 recommendation), title from `<title>` with ` - HumanitiesDC`
  suffix stripped (custom separator), funder hardcoded to "HumanitiesDC".
- `notes['apply_url']` captures the GrantInterface portal URL
  (Q5: explicit at-ingest capture).
- Pass 2: every `wp-content/uploads/*.pdf` link queued and fetched.
- Tests: 5/5 passing.

### dc_eventsdc (eventsdc.com) — one-pass + PDF fetch

- Single GET of `/community/community-grants`, one `OPPORTUNITY_SEEN`,
  funder hardcoded to "Events DC".
- Native `/sites/default/files/*.pdf` links queued; both absolute and
  relative href forms normalized.
- Tests: 4/4 passing.

### Materializer fix (bundled with dc_humanitiesdc)

Discovered while testing dc_humanitiesdc: the materializer was
unconditionally setting `defaults["notes"] = payload.get("notes", {})`,
so the attachment-link `OPPORTUNITY_SEEN` events emitted by
`fetch_attachment()` (which carry no `notes` key) overwrote the
parent's `apply_url`. Same pattern as the title/funder_name_raw bug
fixed in commit a775a5d; applied the analogous one-line gate
(`if payload.get("notes"):`).

This had no observable effect on slice-2 sources or `gov_dc_ost`,
`gov_dc_moca`, `gov_dc_cah` (they don't set notes at ingest). It made
the difference between dc_humanitiesdc's `apply_url` persisting (with
fix) vs. being wiped (without fix) — verified live: the live
dc_humanitiesdc row has `notes={'apply_url':
'https://www.grantinterface.com/Home/Logon?urlkey=wdchumanities'}`.

---

## Phase C — Live verification

### Per-adapter live counts

| Source | RawRecords fetched (incl. PDFs) | OpportunityInstance rows |
|--------|---------------------------------:|--------------------------:|
| gov_dc_cah | 15 (1 index + 14 detail; no PDFs yet) | 14 |
| dc_humanitiesdc | 14 (1 index + 13 PDFs) | 1 |
| dc_eventsdc | 3 (1 index + 2 PDFs) | 1 |

CAH live count is 14 distinct programs vs. the plan's "15–17"
estimate — close enough; Lincoln Theatre (`/publication/`) was
deliberately excluded by the URL pattern, accounting for the
difference.

### find_grants delta

| Profile | Phase A | Phase C | Delta |
|---------|--------:|--------:|------:|
| `dmv_youth_ed_sample.yaml` (no limit) | 348 | 348 | **0** (Tier B/C rows can't match award_min/subject filters) |
| `all.yaml` (DC rows only, no limit) | 40 | 56 | **+16** (14 CAH + 1 HumanitiesDC + 1 EventsDC) |

### Cumulative DC corpus after slice 3a

| Source | Rows | funder_name_raw quality |
|--------|-----:|------------------------|
| gov_dc_ost | 2 | hardcoded — OK |
| gov_dc_moca | 38 | 3/38 (8%) attributed to specific agency; 35/38 fallback |
| gov_dc_cah | 14 | hardcoded — OK |
| dc_humanitiesdc | 1 | hardcoded — OK + apply_url in notes |
| dc_eventsdc | 1 | hardcoded — OK |
| **Total** | **56** | |

### Snapshot

```
python manage.py snapshot_tag corpus-2026-05-23-slice3a-complete
Snapshot 'corpus-2026-05-23-slice3a-complete' created:
event_log_position=329578 manifest=e8babaf4833d...
```

### Test suite

`169 passed in 5.57s` — full grants_ingest suite green, no regressions.

---

## Anomalies / things worth knowing

- **gov_dc_moca agency attribution is 8%.** Already documented in
  Phase A above. Not a slice-3a blocker.
- **gov_dc_cah PDFs absent at survey time.** Expected per plan §1.3;
  adapter will pick them up automatically when FY27 RFAs are posted in
  spring/summer 2026.
- **One CAH detail page title contains a non-breaking space**:
  `'Art Exhibition\xa0Grant'`. Harmless for storage; downstream display
  may want to normalize. Not slice-3a scope.
- **`extract_title` separator was extended in this session** (not in
  `dc_html_util.py` itself, but in the call sites): dc_humanitiesdc
  passes `sep=" - "`, all other DC adapters use the default `sep=" | "`.

---

## Merge readiness

**Ready.** All five slice-3a adapters are committed, tested, and
verified end-to-end against live sources. The materializer notes-overwrite
fix is a strict improvement over prior behavior. No regressions in the
169-test suite.

Outstanding follow-ups (none blocking):
- gov_dc_moca agency extraction precision lift (parse pub-page body,
  not title alone).
- A DC-friendly find_grants profile that doesn't require Tier-A-only
  fields, for the "DC demo" use case — wait until Component 2 starts
  enriching, or accept the `sources:`-filtered profile workaround.
- Slice-2 + slice-3a merge to main.

---

## Branch state at end of session

- 4 new commits ahead of session 1 (daa88d4, 4e77483, 89ac8fc, 1f86d68).
- Pre-existing uncommitted modifications on
  `grants_ingest/adapters/grants_gov.py`, `grants_ingest/opportunity.py`,
  `tests/grants_ingest/test_grants_gov_adapter.py`, and untracked
  migration `0008_opportunity_decimal_max_digits_15.py` — these were
  present at session start and were intentionally left alone.
- Branch `feat/grants-ingest-slice2` not yet pushed; no remote merge.
