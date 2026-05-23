# Grants Ingest — Slice 3a: Five DC Sources

**Date:** 2026-05-23
**Branch:** `feat/grants-ingest-slice2` (slice 2 not yet merged to main as of this writing)
**Authors:** Chris + Claude (Opus-tier planning session)
**Status:** Plan only — no code written this session
**Supersedes:** `docs/plans/2026-05-21-grants-ingest-slice3a-dc-ost.md` (OST + MOCA only)

---

## 1. Source structural survey

All sources fetched live 2026-05-23. All findings are empirical.

### 1.1 learn24.dc.gov — gov_dc_ost

**URLs examined:**
- `https://learn24.dc.gov/page/ost-office-grants` — HTTP 200
- `https://learn24.dc.gov/page/funding-opportunities-0` — HTTP 200
- `https://learn24.dc.gov/robots.txt` — Crawl-delay: 10, standard Drupal template

**Structure:** Static Drupal HTML (no JS). Two single-page indexes — no per-program detail pages. `ost-office-grants` is the live FY27 cycle; `funding-opportunities-0` is archival (FY21–FY24).

**FY27 programs (7):** OST Time Program, OST Small Nonprofit Program, OST Community-Specific CE Program, MOST-DC, OST College and Career Prep, Students in Care of DC Thrives CE, Youth Scholarships CE.

**RFA hosting:** FY27 program-specific RFAs are at `acrobat.adobe.com/id/urn:aaid:sc:...` — ephemeral, not archivable, skip. Supporting materials (overview PDFs, guidebook, scoring rubrics) are at `learn24.dc.gov/sites/default/files/*.pdf` — stable, archivable.

**Third-party portal:** Cityspan (applications at learn24.dc.gov/page/service-providers-0, not an external domain).

**Robots:** Crawl-delay 10. No disallow on `/page/*` or `/sites/default/files/*`.

**Pattern:** Two-pass — index pages → native PDF scan.

---

### 1.2 communityaffairs.dc.gov — gov_dc_moca

**URLs examined:**
- `https://communityaffairs.dc.gov/content/community-grant-program` — HTTP 200
- Sample publication pages: `/publication/fy27-safe-passage-safe-blocks-nofa`, others
- `https://communityaffairs.dc.gov/robots.txt` — Crawl-delay: 10, standard Drupal template

**Structure:** Static Drupal HTML (no JS). Single index page listing ~22 active NOFAs. Each NOFA links to a `/publication/{slug}` page; publication pages link to attachments at `communityaffairs.dc.gov/sites/moca/files/**/*.pdf` or `.docx`.

**Agency distribution:** 22 active NOFAs across OSSE, DOES, DHS, DBH, DC Health, DDOT, DMPED, OVSJG, ONSE, DMPSJ, and others. ~6–8 directly relevant to youth-ed CBO segment.

**OSSE overlap note:** Some OSSE NOFAs appear both here and potentially on osse.dc.gov directly. Content-addressed storage handles the duplicate idempotently.

**Third-party portals:** ZoomGrants, Box (external application links — not fetched).

**Robots:** Crawl-delay 10. No disallow on `/content/*`, `/publication/*`, or `/sites/moca/files/*`.

**Pattern:** Three-pass — index → publication pages → attachments.

---

### 1.3 dcarts.dc.gov — gov_dc_cah

**URLs examined:**
- `https://dcarts.dc.gov/page/grant-programs` — HTTP 200
- `https://dcarts.dc.gov/grants/arts-and-humanities-education-project-grant-program` — sample detail
- `https://dcarts.dc.gov/robots.txt` — Crawl-delay: 10, standard Drupal template

**Structure:** Static Drupal HTML (no JS). Single index page at `/page/grant-programs` in definition-list format — programs delimited by bold linked headings, not semantic `<article>` or `<li>` elements. No pagination.

**Programs (15–17 total on live page):**
Art Bank, Art Exhibition Grant (Curatorial), Arts and Humanities Education Project Grant, Arts and Humanities Fellowship, Capital Projects, Color the Curb, Civic Commissioned Projects, East Arts Grant, Field Trip Experiences, General Operating Support, Juried Exhibition Grant, LiftOff Grant, Lincoln Theatre Rental Support, Projects/Events/Festivals, Public Art Building Communities.

**URL patterns:** Detail pages follow `/grants/{slug}` or `/public-art/{slug}`. No PDF links present on the index page. Detail pages are HTML-only; RFA PDFs are posted seasonally (FY2027 RFAs described as "scheduled for spring/summer 2026" — not yet posted as of survey). When RFA PDFs are posted, they would appear at `dcarts.dc.gov/sites/default/files/**/*.pdf`.

**Third-party portal:** None mentioned on the pages surveyed; CAH appears to use an internal grant management system (no ZoomGrants/Foundant links visible).

**Correction to prompt:** Chris estimated 9 programs; live count is 15–17. The "9 programs" likely refers to the primary competitive grant programs; several entries on the page are informational (Lincoln Theatre rental, Capital Projects) rather than open RFP competitions.

**Robots:** Crawl-delay 10. Same Drupal template as learn24 and communityaffairs.

**Pattern:** Two-pass — index page → detail pages. Regex-scan detail page HTML for `/sites/default/files/*.pdf` links; fetch any found as secondary RawRecords.

---

### 1.4 humanitiesdc.org — dc_humanitiesdc

**URLs examined:**
- `https://humanitiesdc.org/grant-opportunities` — HTTP 200
- `https://humanitiesdc.org/robots.txt` — No Crawl-delay, full access (`Disallow:` empty)
- `https://humanitiesdc.org/sitemap_index.xml` — referenced in robots.txt

**Structure:** WordPress site. Index page at `/grant-opportunities` lists all current programs as bold headings with inline funding details and linked PDF documents. No pagination. No separate detail pages — full program info is on the index.

**Programs (3 current):**
1. DC Oral History Collaborative – Beyond the Archives Grant ($12,000)
2. DC Oral History Collaborative – Continuing Oral History Projects Grant ($8,000–$13,000)
3. General Operating Support Grant ($25,000)

**PDF URL pattern:** `humanitiesdc.org/wp-content/uploads/YYYY/MM/{slug}-rfp_final.pdf` and `{slug}-grant-application.pdf`. These are stable WordPress media uploads, archivable.

**Application portal:** Foundant/GrantInterface at `https://www.grantinterface.com/Home/Logon?urlkey=wdchumanities`. External — capture as `notes['apply_url']`, do not fetch.

**Organization type:** Federally chartered 501(c)(3) humanities council, not a DC government agency. Funded by DC Commission on the Arts and Humanities (CAH) and NEH. The page notes "supported by the DC Commission on the Arts and Humanities."

**Robots:** No Crawl-delay. Full access permitted. No rate limiting required; apply a conservative 1 req/sec as a courtesy.

**Pattern:** Two-pass — index page → native PDFs (same-domain wp-content/uploads links).

---

### 1.5 eventsdc.com — dc_eventsdc

**URLs examined:**
- `https://eventsdc.com/community/community-grants` — HTTP 200
- `https://eventsdc.com/robots.txt` — No Crawl-delay, standard Drupal template
- `https://eventsdc.com/sites/default/files/2025-12/FY26%20Application%20GUIDELINES%205-28-25.pdf` — confirmed reachable

**Structure:** Drupal site, static HTML (no JS for content — accordion behavior is JS but content is in raw HTML). Single index page with no sub-pages. All grant cycle information is on one scrollable page navigated by in-page anchors. Drupal paragraph components delimit sections (e.g., `id="5044"` for FY26 Cycle 1 Grantees).

**Programs:** One recurring program ("Community Grants") with two annual cycles. FY2027 Cycle 1 opens June 15, 2026; deadline August 3, 2026. FY2026 total pool confirmed: $750,000 ($375K/cycle). Individual awards: $5,000–$25,000.

**PDF URL pattern:** `eventsdc.com/sites/default/files/YYYY-MM/{filename}.pdf`. Stable, archivable. Guidelines PDF (~4 pages, 157 KB) and Application Checklist PDF are linked from the index page.

**Application portal:** SmartSimple embedded within the site at `eventsdc.com/community/community-grants`. No external redirect URL to capture.

**Eligibility (from guidelines PDF):** DC-based 501(c)(3) nonprofits for youth sports, performing arts, and cultural arts. Religious organizations eligible if programs are nonsectarian and youth-focused. Alternating-cycle restriction: an org that received a grant in Cycle 1 cannot apply in Cycle 2 of the same FY.

**Entity type:** Washington Convention and Sports Authority — a quasi-public instrumentality of DC government created by DC law (not a 501c3, not a pure executive agency).

**Robots:** No Crawl-delay. `/community/*` and `/sites/default/files/*` are not blocked.

**Pattern:** One-pass + PDF fetch — index page + directly linked PDFs.

---

## 2. Adapter naming and scope

**Decision: five adapters, two namespaces.**

| Source ID | Domain | Funder type | Rationale |
|-----------|--------|-------------|-----------|
| `gov_dc_ost` | learn24.dc.gov | govt_local | DC executive office, public funds |
| `gov_dc_moca` | communityaffairs.dc.gov | govt_local | DC executive clearinghouse |
| `gov_dc_cah` | dcarts.dc.gov | govt_local | DC government commission, statutory body |
| `dc_humanitiesdc` | humanitiesdc.org | public_charity | Federally chartered 501(c)(3), NOT a DC agency |
| `dc_eventsdc` | eventsdc.com | govt_local | DC instrumentality (WCSA), public funds |

**Naming call: `dc_*` for HumanitiesDC and Events DC, not `gov_dc_*`.**

The `gov_dc_*` prefix is reserved for DC executive-branch agencies (`funder_type = govt_local` sourced from agency appropriations). HumanitiesDC is a federally chartered 501(c)(3) with an independent board — it is funded by CAH and NEH but is not a DC government agency and does not draw from DC agency appropriations directly. Using `gov_dc_humanitiesdc` would be false and would mislead the funder_type inference.

Events DC (Washington Convention and Sports Authority) is a closer call — it is a DC government instrumentality created by DC Code §10-1202.01, authorized to issue grants from its own operating budget. The `dc_eventsdc` source ID signals "DC-based, public-ish funder, not a strict DC executive agency." If the `gov_dc_*` prefix were applied, it should imply a DC executive-branch agency; WCSA does not fit that definition. The `dc_*` prefix is accurate and extensible (future MD or VA quasi-public funders could use `md_*` or `va_*` by analogy).

**`dc_*` prefix creates a new namespace.** Future sources that are DMV-based but not strictly government: `dc_humanitiesdc`, `dc_eventsdc`, eventually `md_artscouncil`, `va_arts`, etc. Add a note to the spec explaining the distinction between `gov_dc_*` and `dc_*`.

---

## 3. Shared adapter utilities

All five adapters share three patterns:
1. Regex-based title extraction from raw HTML bytes
2. Regex-based href scanning for URL discovery
3. PDF fetch loop with 50 MB cap

**Recommendation: extract into `grants_ingest/adapters/dc_html_util.py`** (utility module, not a base class). The run() topologies diverge too much (one-pass, two-pass, three-pass) for a shared base class to be clean. A utility module provides the helpers without forcing inheritance.

Contents of `dc_html_util.py`:

```python
# Shared utilities for DC HTML adapters (gov_dc_*, dc_*)
import html
import re

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)

def extract_title(body: bytes, suffix: str = "") -> str:
    """Extract <title> text from raw HTML, strip an optional suffix."""
    m = _TITLE_RE.search(body.decode("utf-8", errors="ignore"))
    if not m:
        return ""
    title = html.unescape(m.group(1)).strip()
    if suffix and title.endswith(suffix):
        title = title[: -len(suffix)].strip()
    return title

def scan_hrefs(body: bytes, pattern: re.Pattern) -> list[str]:
    """Return all href values matching pattern from raw HTML bytes."""
    text = body.decode("utf-8", errors="ignore")
    return [m.group(1) for m in pattern.finditer(text)]

# Known DC agency abbreviations → canonical names for gov_dc_moca
DC_AGENCY_NAMES: dict[str, str] = {
    "OSSE": "DC Office of the State Superintendent of Education",
    "DOES": "DC Department of Employment Services",
    "DHS": "DC Department of Human Services",
    "DBH": "DC Department of Behavioral Health",
    "DC Health": "DC Department of Health",
    "DDOT": "DC Department of Transportation",
    "DMPED": "DC Office of Planning and Economic Development",
    "DHCD": "DC Department of Housing and Community Development",
    "OVSJG": "DC Office of Victim Services and Justice Grants",
    "ONSE": "DC Office of Neighborhood Safety and Engagement",
    "DMPSJ": "DC Office of Migrant Services and Public Health Justice",
    "DPR": "DC Department of Parks and Recreation",
    "DCCAH": "DC Commission on the Arts and Humanities",
    "OAG": "DC Office of the Attorney General",
    "MPD": "DC Metropolitan Police Department",
}

_AGENCY_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in DC_AGENCY_NAMES) + r")\b"
)

def extract_moca_agency(title: str) -> str | None:
    """Return the canonical agency name from a NOFA title, or None."""
    m = _AGENCY_RE.search(title)
    if not m:
        return None
    return DC_AGENCY_NAMES[m.group(1)]
```

The `_extract_title` helper was already specified in the slice 3a OST+MOCA plan; this plan formalizes its module location and adds the `scan_hrefs` and MOCA agency utilities.

**Shared PDF fetch method:** Rather than duplicating `_fetch_pdf` across adapters, define it once in `dc_html_util.py` as a standalone function:

```python
def fetch_pdf(
    url: str,
    client: httpx.Client,
    store,
    event_log,
    source_id: str,
    parent_sha: str,
    result: AdapterRunResult,
    size_cap: int = 50 * 1024 * 1024,
) -> str | None:
    """Fetch a PDF, store content-addressed, return content_sha or None."""
    # HEAD check, 50MB cap, fetch, store, emit SEEN event
    # Returns content_sha if successful, None otherwise
```

This replaces the duplicated `_fetch_pdf` method in `DCOSTAdapter`, `DCMOCAAdapter`, `DCAHAdapter`, etc.

---

## 4. Source register entries

Replace stale entries in `docs/specs/grant_ingestion.md` section 5:

**Remove (confirmed dead):**
- `gov_dc_opportunities` — `opportunities.dc.gov` returns connection refused (2026-05-23)
- `gov_dc_opgs` — `opgs.dc.gov` redirects to ServesDC (volunteerism, not grants)
- CYITC reference — DC Children and Youth Investment Trust defunct since 2017; OST Office supersedes

**Add:**

| ID | Source | Tier | Cadence | Adapter style |
|----|--------|------|---------|---------------|
| `gov_dc_ost` | DC OST Office (learn24.dc.gov) | B | Weekly | Two-pass: index + native PDF |
| `gov_dc_moca` | DC MOCA clearinghouse (communityaffairs.dc.gov) | B | Weekly | Three-pass: index → pub pages → attachments |
| `gov_dc_cah` | DC Commission on Arts and Humanities (dcarts.dc.gov) | B | Weekly | Two-pass: index → detail pages + PDF scan |
| `dc_humanitiesdc` | HumanitiesDC (humanitiesdc.org) | B | Weekly | Two-pass: index + native PDFs |
| `dc_eventsdc` | Events DC (eventsdc.com) | B | Weekly | One-pass + PDF fetch |

---

## 5. Funder auto-create policy

### gov_dc_ost
Single funder, hardcoded:
- `canonical_name` = "DC Office of Out of School Time Grants and Youth Outcomes"
- `funder_type` = `govt_local`
- `notes['parent_agency']` = "Deputy Mayor for Education"

### gov_dc_moca
**Do NOT create a funder for "MOCA" or "DC Mayor's Office of Community Affairs."**

Each NOFA's issuing agency is the funder. At ingest time, `funder_name_raw` is extracted from the publication page title using `extract_moca_agency()`. The closed set of DC agencies (see `DC_AGENCY_NAMES` dict in `dc_html_util.py`) is the lookup table. Auto-create a `Funder` row on first sighting:

- `canonical_name` = value from `DC_AGENCY_NAMES` (e.g., "DC Office of the State Superintendent of Education")
- `funder_type` = `govt_local`
- `notes['abbreviation']` = the matched abbreviation (e.g., "OSSE")
- `notes['clearinghouse']` = "DC Mayor's Office of Community Affairs"

If no agency name is found in the title: `funder_name_raw = "DC Government (agency unresolved)"`, add to the manual-review queue. This is the fallback for NOFAs that don't name their agency in the title.

### gov_dc_cah
Single funder, hardcoded:
- `canonical_name` = "DC Commission on the Arts and Humanities"
- `funder_type` = `govt_local`
- `notes['abbreviation']` = "CAH" (also known as "DC Arts" in colloquial use)

### dc_humanitiesdc
Single funder:
- `canonical_name` = "HumanitiesDC"
- `funder_type` = `public_charity`
- `notes['full_name']` = "DC Humanities Council"
- `notes['federal_charter']` = True
- `notes['funders']` = ["DC Commission on the Arts and Humanities", "National Endowment for the Humanities"]

### dc_eventsdc
Single funder:
- `canonical_name` = "Events DC"
- `funder_type` = `govt_local`
- `notes['full_name']` = "Washington Convention and Sports Authority"
- `notes['quasi_public']` = True

Note on `funder_type` for Events DC: the Funder schema enumerates `govt_local` as the closest match for a DC instrumentality. If a `quasi_govt` type is added later, Events DC should be migrated. The `notes['quasi_public']` flag preserves this distinction. See open question Q4.

---

## 6. OpportunityInstance fields produced at ingest

Per Tier B/C principle and slice 3 scope: **title + funder_name_raw + source URL + raw record only.** All other fields deferred to Component 2.

| Field | gov_dc_ost | gov_dc_moca | gov_dc_cah | dc_humanitiesdc | dc_eventsdc |
|-------|------------|-------------|------------|-----------------|-------------|
| `title` | From `<title>`, strip ` \| learn24` | From `<title>`, strip ` \| Mayors Office...` | From `<title>`, strip ` \| dcarts` | From bold heading (index page regex) | From `<title>`, strip ` \| Events DC` |
| `funder_name_raw` | Hardcoded OST Office | Extracted from NOFA title via `extract_moca_agency()` | Hardcoded CAH | Hardcoded HumanitiesDC | Hardcoded Events DC |
| `source_id` | "gov_dc_ost" | "gov_dc_moca" | "gov_dc_cah" | "dc_humanitiesdc" | "dc_eventsdc" |
| `external_id` | "gov_dc_ost:{page_url}" | "gov_dc_moca:{pub_url}" | "gov_dc_cah:{detail_url}" | "dc_humanitiesdc:{program_slug}" | "dc_eventsdc:{cycle_id}" |
| `notes['apply_url']` | — | External portal URLs (ZoomGrants) | — | GrantInterface URL | — |
| All other fields | None / deferred | None / deferred | None / deferred | None / deferred | None / deferred |

**HumanitiesDC title extraction:** The index page uses bold headings rather than a separate `<title>` tag per program. Use a regex scan for bold-heading patterns (`<strong>` or `<b>` tags with program-name content). Since the entire grant listing is on one page, use the program heading as the title rather than the page title. This is a shallow text extraction (no CSS selectors) that is defensible under the Tier B/C rule — the heading structure is a raw-bytes pattern, not a layout assumption.

Alternatively, emit one OPPORTUNITY_SEEN per index page fetch (simpler, consistent with gov_dc_ost), using the page title as the title. This is the V1 recommendation — one record per page fetch, not one per program. Component 2 will split them.

**Events DC external_id:** The index page lists multiple past cycles as anchor sections (e.g., `#5044` for FY26 C1, `#4672` for FY25 C2). Use `dc_eventsdc:community-grants-fy27-c1` etc. as the external_id, derived from the cycle heading text, not the DOM `id` attribute (which is an auto-increment Drupal paragraph ID, unstable across re-renders). If cycle heading detection is complex, fall back to `dc_eventsdc:community-grants-index` for the whole page.

---

## 7. PDF handling

All adapters mirror the grants_gov/slice-2 pattern:
- HEAD request first to check Content-Length (50 MB hard cap)
- If HEAD omits Content-Length: proceed with streaming GET, abort if download exceeds 50 MB
- Store content-addressed as a separate RawRecord
- Link to parent opportunity via `extra_content_shas` in OPPORTUNITY_SEEN event
- Emit a second OPPORTUNITY_SEEN with parent sha + attachment sha so materializer M2M-links them

**Per-source PDF sources:**

| Source | PDF URL pattern | DOCX? |
|--------|-----------------|-------|
| gov_dc_ost | `learn24.dc.gov/sites/default/files/**/*.pdf` only | No |
| gov_dc_moca | `communityaffairs.dc.gov/sites/moca/files/**/*.pdf` | Yes — store with correct MIME |
| gov_dc_cah | `dcarts.dc.gov/sites/default/files/**/*.pdf` (seasonal — not present at survey time) | No |
| dc_humanitiesdc | `humanitiesdc.org/wp-content/uploads/**/*.pdf` | No |
| dc_eventsdc | `eventsdc.com/sites/default/files/**/*.pdf` | No |

**Skip lists (do not fetch):**
- All `acrobat.adobe.com` URLs (gov_dc_ost ephemeral RFAs)
- All `box.com`, `drive.google.com` links (gov_dc_moca external portals)
- All `grantinterface.com` links (dc_humanitiesdc application portal)
- Log `EXTERNAL_LINK_UNARCHIVABLE` for Adobe Acrobat URLs from gov_dc_ost

**gov_dc_cah PDF note:** No PDFs were present at survey time. The adapter should still scan detail page HTML for `/sites/default/files/*.pdf` links and fetch them if found. RFA PDFs for FY27 are expected to appear on existing detail pages in spring/summer 2026; the adapter will pick them up automatically on the next weekly run after they're posted.

---

## 8. Pre-filtering at ingest

**gov_dc_ost:** No pre-filtering. All 7 FY27 programs are org-facing grants (including Youth Scholarships CE, which is administered by coordinating entities, not families). No family-facing scholarship content appears on the portal.

**gov_dc_moca:** No pre-filtering. Store all ~22 NOFAs as raw records per Tier B/C principle. The 14 off-segment NOFAs (EVs, housing, Chinatown lease incentive) add trivial volume (~14 small HTML pages + PDFs per weekly run). Component 2's relevance classifier handles downstream filtering. A configurable `title_deny_patterns` list could be added later if the unfiltered volume becomes operationally noisy — not recommended for V1.

**gov_dc_cah:** No pre-filtering. 15–17 programs span a mix of youth-ed relevant (Arts Education, General Operating Support, East Arts) and less-relevant (Color the Curb, Lincoln Theatre rental). Volume is small; store all.

**dc_humanitiesdc:** No pre-filtering. Only 3 active programs. All are potentially relevant.

**dc_eventsdc:** No pre-filtering. Single program, two annual cycles. Both cycles are in scope.

---

## 9. Cadence

| Source | Recommended cadence | Robots.txt constraint | Rationale |
|--------|--------------------|-----------------------|-----------|
| `gov_dc_ost` | Weekly | Crawl-delay: 10 (→ 0.1 req/s) | OST runs one grant cycle per FY; sub-week granularity adds no value |
| `gov_dc_moca` | Weekly | Crawl-delay: 10 (→ 0.1 req/s) | NOFAs posted irregularly but not sub-weekly |
| `gov_dc_cah` | Weekly | Crawl-delay: 10 (→ 0.1 req/s) | Annual grant cycles; RFAs posted seasonally |
| `dc_humanitiesdc` | Weekly | None (→ 1 req/s courtesy) | 3 programs, static index |
| `dc_eventsdc` | Weekly | None (→ 1 req/s courtesy) | Two cycles per year |

**Run time estimates (full run with PDF fetches):**
- gov_dc_moca: ~22 pub pages + ~22 PDFs at 0.1 req/s ≈ 7–8 minutes
- gov_dc_cah: ~17 detail pages (no PDFs currently) at 0.1 req/s ≈ 3 minutes
- gov_dc_ost: 2 index pages + ~5 native PDFs at 0.1 req/s ≈ 1 minute
- dc_humanitiesdc: 1 index + ~6 PDFs at 1 req/s ≈ 10 seconds
- dc_eventsdc: 1 index + ~2 PDFs at 1 req/s ≈ 5 seconds

All five adapters can run sequentially in one scheduled weekly job; total runtime ~12 minutes.

---

## 10. Test fixtures plan

Mirror slice 2's synthetic fixture pattern. No real DC government HTML or PDFs in the test suite.

### gov_dc_ost fixtures

| Fixture | Tests |
|---------|-------|
| `ost_index.html` | 2 native PDF links + 2 Acrobat links → discovers 2, skips 2 |
| `ost_supporting.pdf` | Minimal PDF; secondary RawRecord + extra_content_shas |
| `ost_index_no_pdfs.html` | Only Acrobat links → OPPORTUNITY_SEEN emitted, no PDF fetch |
| Idempotency: same HTML twice → no duplicate RawRecord |
| PDF > 50 MB → OPPORTUNITY_FILTERED |
| Robots.txt blocked path → ROBOTS_BLOCKED, no OPPORTUNITY_SEEN |

### gov_dc_moca fixtures

| Fixture | Tests |
|---------|-------|
| `moca_index.html` | 3 `/publication/` links + 1 external → discovers 3, skips 1 |
| `moca_pub_with_agency.html` | Title "FY27 OSSE Pre-K Enhancement NOFA" → `funder_name_raw = "DC Office of the State Superintendent of Education"` |
| `moca_pub_no_agency.html` | Title without agency match → `funder_name_raw = "DC Government (agency unresolved)"` |
| `moca_pub_with_pdf.html` | 2 native PDF attachments → 2 secondary RawRecords |
| `moca_pub_with_docx.html` | 1 DOCX → correct MIME type stored |
| Idempotency: same publication URL twice → no duplicate |
| Robots.txt blocked → ROBOTS_BLOCKED |

### gov_dc_cah fixtures

| Fixture | Tests |
|---------|-------|
| `cah_index.html` | Synthetic index with 3 `/grants/` links + 1 `/public-art/` link → discovers all 4 |
| `cah_detail_with_pdf.html` | Detail page with 1 native PDF link → PDF queued |
| `cah_detail_no_pdf.html` | Detail page (no PDF yet) → OPPORTUNITY_SEEN, no PDF fetch |
| Idempotency: same detail URL twice → no duplicate |
| Title suffix stripping: ` \| dcarts` removed correctly |

### dc_humanitiesdc fixtures

| Fixture | Tests |
|---------|-------|
| `humanitiesdc_index.html` | Index with 3 programs, 6 PDF links (2 per program) → 6 PDFs queued |
| `humanitiesdc_rfp.pdf` | Minimal PDF → stored as secondary RawRecord |
| Idempotency: same index twice → no duplicate |
| One OPPORTUNITY_SEEN per index page fetch (not per program) |

### dc_eventsdc fixtures

| Fixture | Tests |
|---------|-------|
| `eventsdc_index.html` | Index with 1 guidelines PDF + 1 checklist PDF → both queued |
| `eventsdc_guidelines.pdf` | Minimal PDF → secondary RawRecord |
| Idempotency |
| Title extraction: ` \| Events DC` suffix stripped |

### Shared cross-adapter test

One shared idempotency test in `test_dc_html_util.py`:
- `extract_title()` with suffix stripping
- `scan_hrefs()` with a test pattern
- `extract_moca_agency()` with positive and negative cases
- `fetch_pdf()` helper with size-cap enforcement

---

## 11. Commit breakdown

**Recommended split: two Sonnet sessions, 3+2 split.**

Session 1 covers the two more complex adapters (three-pass MOCA, plus OST) and establishes the shared utility module. Session 2 covers the three simpler adapters. If Session 1 reveals problems with the shared utilities or the MOCA agency extraction, Session 2 can adapt before building on top.

### Session 1: gov_dc_ost + gov_dc_moca (6 commits)

| # | Commit | Contents |
|---|--------|----------|
| 1 | `feat(grants_ingest): dc_html_util — shared title/href/PDF helpers` | `adapters/dc_html_util.py` with `extract_title`, `scan_hrefs`, `DC_AGENCY_NAMES`, `extract_moca_agency`, `fetch_pdf` |
| 2 | `test(grants_ingest): dc_html_util utility functions` | `tests/grants_ingest/test_dc_html_util.py` |
| 3 | `feat(grants_ingest): gov_dc_ost adapter — index + native PDF fetch` | `adapters/dc_ost.py` |
| 4 | `test(grants_ingest): gov_dc_ost adapter — 6 test cases` | `tests/grants_ingest/fixtures/dc_ost/` + `tests/grants_ingest/test_dc_ost_adapter.py` |
| 5 | `feat(grants_ingest): gov_dc_moca adapter — three-pass index/pub/attachment fetch` | `adapters/dc_moca.py` |
| 6 | `test(grants_ingest): gov_dc_moca adapter — 7 test cases` | `tests/grants_ingest/fixtures/dc_moca/` + `tests/grants_ingest/test_dc_moca_adapter.py` |

### Session 2: gov_dc_cah + dc_humanitiesdc + dc_eventsdc (7 commits)

| # | Commit | Contents |
|---|--------|----------|
| 7 | `feat(grants_ingest): gov_dc_cah adapter — index + detail pages + PDF scan` | `adapters/dc_cah.py` |
| 8 | `test(grants_ingest): gov_dc_cah adapter — 4 test cases` | `tests/grants_ingest/fixtures/dc_cah/` + `tests/grants_ingest/test_dc_cah_adapter.py` |
| 9 | `feat(grants_ingest): dc_humanitiesdc adapter — index + native PDF fetch` | `adapters/dc_humanitiesdc.py` |
| 10 | `test(grants_ingest): dc_humanitiesdc adapter — 4 test cases` | `tests/grants_ingest/fixtures/dc_humanitiesdc/` + `tests/grants_ingest/test_dc_humanitiesdc_adapter.py` |
| 11 | `feat(grants_ingest): dc_eventsdc adapter — index + PDF fetch` | `adapters/dc_eventsdc.py` |
| 12 | `test(grants_ingest): dc_eventsdc adapter — 4 test cases` | `tests/grants_ingest/fixtures/dc_eventsdc/` + `tests/grants_ingest/test_dc_eventsdc_adapter.py` |
| 13 | `feat(grants_ingest): wire all 5 DC adapters into ingest_run + spec update` | `management/commands/ingest_run.py` (add 5 sources to `_build_adapter()`), `docs/specs/grant_ingestion.md` (section 5 updates per §4 above) |

**Total: 13 commits across 2 sessions.** Each session is independently shippable — Session 1 can be live-verified before starting Session 2.

---

## 12. Open questions for Chris

**Q1 — gov_dc_moca agency extraction:** The plan proposes extracting `funder_name_raw` from NOFA titles using a regex against the `DC_AGENCY_NAMES` dict. This means `funder_name_raw` varies per NOFA (e.g., "DC Office of the State Superintendent of Education" for OSSE NOFAs). Is this the right approach, or should we fall back to `funder_name_raw = "DC Mayor's Office of Community Affairs"` at ingest and let Component 2 resolve the issuing agency? The regex approach is more useful downstream but adds a small amount of title-parsing logic to an otherwise raw-bytes adapter.

**Q2 — dc_humanitiesdc: one OPPORTUNITY_SEEN per page or per program?** The index page at `/grant-opportunities` lists 3 programs. Options: (a) emit one OPPORTUNITY_SEEN for the entire index page URL (simpler, consistent with gov_dc_ost), or (b) emit one per program by parsing program headings (3 records, closer to the correct granularity). Option (a) is recommended for V1 — Component 2 splits them. Option (b) requires shallow title extraction from headings, which is defensible but adds adapter logic.

**Q3 — funder_type for Events DC:** The `Funder.funder_type` enum in the spec is: `private_foundation / community_foundation / public_charity / govt_federal / govt_state / govt_local / corporate / united_way`. There is no `quasi_govt`. The plan assigns `govt_local` to Events DC (Washington Convention and Sports Authority) on the grounds that it is a DC government instrumentality distributing public DC funds. Confirm this is acceptable, or add `quasi_govt` to the enum (a migration) — this is the kind of schema change that requires Opus-tier review per CLAUDE.md.

**Q4 — gov_dc_cah program scope:** The live page lists 15–17 programs, not the ~9 in Chris's estimate. Several are narrowly relevant (Lincoln Theatre rental support, Capital Projects) rather than open competitive grants a CBO would apply for. Should the adapter fetch all detail pages, or apply a title-based pre-filter to skip clearly non-competitive programs? Recommendation: fetch all (volume is small; 17 detail pages at 0.1 req/s is ~3 minutes). Surfacing the question in case Chris wants to narrow scope.

**Q5 — dc_humanitiesdc application portal URL in notes:** The GrantInterface portal URL (`https://www.grantinterface.com/Home/Logon?urlkey=wdchumanities`) is the same for all HumanitiesDC programs. Should it be captured as `notes['apply_url']` on each OPPORTUNITY_SEEN payload, or is it sufficient to leave it as raw bytes in the fetched index page (where Component 2 can extract it)? Capturing it explicitly at ingest costs one line of adapter code and makes it immediately queryable.

**Q6 — Adobe Acrobat gap (gov_dc_ost):** The live FY27 OST program RFAs are at Acrobat shared-document URLs. The adapter will not fetch them — the `EXTERNAL_LINK_UNARCHIVABLE` event is the only trace. Is this coverage gap acceptable for V1? The index page HTML (stored as a RawRecord) contains program descriptions, deadlines, and Cityspan application instructions; the full RFA PDFs are not captured. Confirmed "acceptable for V1" in the prior planning session — including here for explicit sign-off.

**Q7 — Spec namespace note:** The plan introduces a `dc_*` prefix for non-`gov_dc_*` DC sources. Should this distinction (government agency vs. quasi-public/501c3) be documented as a naming convention in the spec's source register header? Recommended yes — one sentence explaining `gov_dc_*` = DC executive agency, `dc_*` = DC-based public/quasi-public funder, `cf_*` = community foundation, etc.

---

## 13. Out of scope

- `gov_dc_osse` (osse.dc.gov direct — future slice; OSSE grants visible through MOCA and learn24 are captured as a side effect of gov_dc_moca and gov_dc_ost)
- `gov_dc_dpr` (dpr.dc.gov — out of scope for this slice; low OST relevance)
- DMPED grants (business-focused, low yield for youth-ed CBOs)
- DOEE grants (environment/sustainability focus)
- Community foundations (`cf_*` — separate slice)
- Maryland and Virginia sources (slice 3b, 3c)
- PDF content parsing or field extraction (Component 2)
- LLM extraction pass
- State-transition state machine
- Relevance ranking or donor-surface changes
- `find_grants` CLI changes (existing command picks up new rows automatically once materializer runs)
- Railway cron wiring
- Any changes to existing adapters (irs_990pf, propublica_np, grants_gov)
