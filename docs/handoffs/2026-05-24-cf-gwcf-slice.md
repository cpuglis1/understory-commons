# Handoff — cf_gwcf Adapter (Slice 4)

**Date:** 2026-05-24
**Branch:** `feat/grants-ingest-structured-fields`
**Snapshot:** `corpus-2026-05-24-cf-gwcf` (event_log_position=329757)

---

## Live-site count vs ingested-row count

| Item | Count |
|------|------:|
| Open opportunities on GWCF site (`/open-grant-opportunities`) | **1** |
| `cf_gwcf` OpportunityInstance rows after ingest | **1** |

Match verified by:
- Manually browsing `https://www.thecommunityfoundation.org/open-grant-opportunities` — one listing card visible (McMillan Scholarship Program)
- `fetched=2` in ingest output = 1 index page + 1 detail page (correct)
- `find_grants --profile profiles/all.yaml` returns 1 cf_gwcf row

No discrepancies to explain.

---

## Ingested row — McMillan Scholarship Program

| Field | Value |
|-------|-------|
| `title` | "McMillan Scholarship Program" |
| `funder_name_raw` | "Greater Washington Community Foundation" |
| `status` | open |
| `application_close_at` | 2026-06-29 23:59:59 UTC |
| `award_min` | null |
| `award_max` | $5,000.00 |
| `subject_areas` | [] |
| `eligibility` | {} |
| `notes['apply_url']` | `https://us.grantrequest.com/application.aspx?sid=5491&fid=35435` |
| `notes['description']` | 400-char excerpt of grant body text (eligibility, program name, purpose) |

---

## Per-field extraction coverage

| Field | Present on source | Extracted | Notes |
|-------|:-----------------:|:---------:|-------|
| title | ✓ | ✓ | em-dash separator `" — "` handled; GWCF suffix stripped |
| funder_name_raw | n/a | ✓ | hardcoded |
| application_close_at | ✓ | ✓ | "June 29, 2026" with "deadline" context; `extract_deadline()` |
| application_open_at | ✗ | n/a | not stated on page |
| award_max | ✓ | ✓ | "up to $5,000"; `extract_award_range()` |
| award_min | ✗ | n/a | no floor stated |
| typical_award | ✗ | n/a | not stated |
| eligibility.org_type | ✗ | null | scholarship language; no 501c3/nonprofit text present |
| subject_areas | ✗ | [] | title "McMillan Scholarship Program" has no keyword hits in `_TITLE_KEYWORD_MAP` |
| notes['apply_url'] | ✓ | ✓ | `grantrequest.com` portal link captured |
| notes['description'] | ✓ | ✓ | 1,500-char excerpt of `<main>` content; covers eligibility prose |
| notes['program_name_raw'] | ✓ | not set | "McMillan Scholarship Fund (MSF)" appears in body but no reliable extractor without a new rule; description excerpt contains it |

---

## North Star check

| Criterion | Satisfied? | Detail |
|-----------|:----------:|--------|
| (a) active (open or upcoming) | ✓ | deadline June 29, 2026 |
| (b) award amount known | ✓ | up to $5,000 |
| (c) eligible org identifiable | partial | this is a student scholarship (Ward 1 + Ward 5, specified fields of study); not a CBO/nonprofit grant. Eligibility prose is captured in `notes['description']` |
| (d) funder DC/MD/VA non-federal | ✓ | GWCF, DC-based community foundation |

3 of 4 North Star criteria satisfied. The scholarship does not target 501(c)(3) nonprofits; the eligible applicant is an individual student. This is correctly ingested (coverage rule: ingest everything the source publishes) and the description field surfaces the eligibility context.

---

## Implementation notes

**Spec index paths were wrong.** The spec listed `/grants/open-opportunities` and `/grants/active-funds` — both 404. The correct index is `/open-grant-opportunities`. Adapter uses the correct URL.

**Two live issues fixed during ingest:**

1. **Title separator**: Squarespace title tags use ` — ` (em dash, `&mdash;`) not ` - ` as the site-name separator. `extract_title(body, sep=" — ")` handles it correctly.

2. **Description noise**: `html_to_text()` left Squarespace's `<script>` JSON context blob and nav links in the output. Fixed by extracting from `<main>` first, then stripping `<script>`/`<style>` blocks before running through `html_to_text`. Description now starts from grant body text.

**Initiative-specific pages checked and excluded**: Brilliant Futures, Health Equity Fund, Partnership to End Homelessness, Thrive Prince George's — all informational/closed programs, no open RFPs, not listed on the index page.

**PDF scan is wired but dormant**: `_PDF_RE` is in place; no PDFs were linked on any GWCF page fetched today. Will pick them up automatically if PDFs are added.

**apply_url is dynamic** (unlike dc_humanitiesdc which hardcodes the portal URL). Captured via `_APPLY_URL_RE` scanning for known portal domains in page hrefs.

---

## Does GWCF yield justify building cf_cfnova / cf_arlcf next?

**Honest assessment: thin.** GWCF's open-opportunity set is currently 1 scholarship targeting individual students — not a CBO grant. This one row does not satisfy North Star criterion (c).

GWCF runs larger initiatives (Health Equity Fund, Partnership to End Homelessness, Thrive PG's, Brilliant Futures) but these are closed programs or invitation-only — not open RFPs.

**Recommendation**: Before expanding to `cf_cfnova` or `cf_arlcf`, evaluate whether those sites have meaningfully more open CBO-targeted RFPs right now. If the community foundation open-opportunity cycle is thin across the board (likely — most CF grant rounds open in fall/winter), a higher-yield next step might be:
- `pf_*` private foundation adapters for foundations with rolling or always-open application windows
- `uwnca` (United Way NCA) which runs regular community impact grant cycles
- Revisit `cf_*` adapters in September when fall cycles open

The adapter is production-ready and will pick up new GWCF opportunities automatically on each weekly run.

---

## Known issues (pre-existing, not introduced here)

- `gov_dc_ost` "Funding Opportunities" row still shows `award_max=$22.1M` — the total-pool extractor fix (slice 3b) corrected the rule but didn't clear the already-materialized value. Not a cf_gwcf issue.
- RuntimeWarning about naive datetimes in `application_close_at` — pre-existing across all DC adapters; the datetime is stored as UTC in the DB but the warning fires during materialization. Not introduced here.
