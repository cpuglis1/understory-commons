# Grants Ingest — Slice 3a: DC OST Office + DC MOCA Grants Clearinghouse

**Date:** 2026-05-23
**Branch:** `feat/grants-ingest-slice2` (no merge to main yet as of this writing)
**Authors:** Chris + Claude (Opus-tier planning session)
**Status:** Plan only — no code written this session

---

## 1. Live source survey

Fetched live 2026-05-23. All findings are empirical.

### 1.1 learn24.dc.gov

**URLs examined:**
- `https://learn24.dc.gov/page/ost-office-grants` — primary grants page, HTTP 200
- `https://learn24.dc.gov/page/funding-opportunities-0` — archival grants page, HTTP 200
- `https://learn24.dc.gov/robots.txt` — confirmed

**Page structure:**
Both pages are static Drupal HTML (no JS required). No separate detail page exists per grant program — the entire grant listing is on the index page. `ost-office-grants` is the live-cycle page (FY27 active); `funding-opportunities-0` is archival (FY21–FY24).

**FY27 active programs (7 listed on ost-office-grants):**
1. Out of School (OST) Time Program
2. OST Small Nonprofit Program
3. OST Community-Specific Coordinating Entity Program
4. My Out of School Time-DC Program (MOST-DC)
5. OST College and Career Prep Program
6. Students in the Care of DC Thrives Coordinating Entity Program
7. Youth Scholarships Coordinating Entity Program

**RFA document hosting — critical finding:**
FY27 RFA documents are split across two hosting locations:
- **Adobe Acrobat shared links** (`acrobat.adobe.com/id/urn:aaid:sc:...`) — this is where the live FY27 program-specific RFAs live. These are ephemeral shared-document URLs that will break when the OST Office unpublishes them. They are external, not archivable via normal HTTP fetch, and must NOT be followed by the adapter.
- **Native `learn24.dc.gov/sites/default/files/` links** — stable URLs to supporting materials: grant overview PDFs, Grantee Guidebook, Scoring Rubrics, User Guide, General Eligibility Requirements. These are archivable and should be fetched.

**Application management:** Cityspan (`cityspan.com`), not Submittable or Foundant. Application links go to `learn24.dc.gov/page/service-providers-0`.

**Pagination:** None. Both pages are single-scroll.

**RSS / JSON feeds:** None found at `/feed`, `/feeds`, or `/sitemap.xml`.

**robots.txt:**
Standard Drupal template. All general bots allowed. `Crawl-delay: 10`. No disallow rules on `/page/*` or `/sites/default/files/*`. SemrushBot and bytespider are blocked (irrelevant to us). The 10-second crawl delay applies.

### 1.2 opgs.dc.gov — DEFUNCT

**Critical correction to the prompt:** `opgs.dc.gov` no longer hosts a grants portal. It redirects unconditionally to `https://communityaffairs.dc.gov/servedc` (the Mayor's Office of Volunteerism and Partnerships — a completely different unit). Both `opgs.dc.gov` and `opgs.dc.gov/page/grant-opportunities` redirect to the same ServesDC page. There is no "DC OPGS" grants portal to ingest from. Do not chase this URL.

The entity described in the spec as `gov_dc_opportunities` (`opportunities.dc.gov`) is also dead — connection refused.

### 1.3 communityaffairs.dc.gov — the real DC multi-agency grants clearinghouse

**URL:** `https://communityaffairs.dc.gov/content/community-grant-program` — this is the live successor to what the spec called `gov_dc_opportunities`. It is published by the DC Mayor's Office of Community Affairs (MOCA).

**Index page structure:** A single scrollable HTML page listing all active NOFAs across multiple DC agencies. Each NOFA has 1–3 links:
- A "NOFA" or "Notice of Funding" link → goes to a `/publication/{slug}` page on communityaffairs.dc.gov
- An "Attachments" link → also goes to `/publication/{slug}` (may be a companion page with just files)
- An "Application Links" link → goes to external portals (ZoomGrants, Box, etc.)

**Publication page structure (confirmed on two samples):**
- URL pattern: `communityaffairs.dc.gov/publication/{slug}`
- Title in `<title>` tag and `<h1>` (consistent, e.g. "FY27 Safe Passage, Safe Blocks NOFA")
- Native attachment links at: `communityaffairs.dc.gov/sites/moca/files/dc/sites/moca/publication/attachments/*.pdf` (and occasionally `.docx`)
- No external PDF hosting (unlike learn24 which uses Acrobat for current-cycle docs)

**Active NOFA count (as of survey):** ~22 NOFAs across all DC agencies. Relevant to CBO youth/education segment: ~6–8 (OSSE, DOES youth workforce, youth safety, community development, pre-K). Remainder are healthcare, housing, infrastructure — not relevant to our CBO target but should still be ingested as raw records per Tier B/C principle.

**OSSE overlap finding:** Two OSSE grants appear on communityaffairs.dc.gov (OSSE FY26 SOAR Act Facilities Grant, OSSE FY27 Pre-K Enhancement). When a future `gov_dc_osse` adapter fetches `osse.dc.gov` directly, these may appear there too. Content-addressed storage handles the duplicate idempotently (same bytes → same sha).

**RSS / JSON feeds:** None found. GovDelivery email subscription list exists for funding alerts but is not machine-readable.

**robots.txt:** Same standard Drupal template as learn24. Crawl-delay: 10. No disallow on `/content/*` or `/publication/*` or `/sites/moca/files/*`. Same bot-blocking rules (SemrushBot, bytespider).

---

## 2. Adapter naming and scope

**Recommendation: two adapters, portal-scoped.**

| Source ID | Domain | Scope |
|-----------|--------|-------|
| `gov_dc_ost` | learn24.dc.gov | DC OST Office grant programs only |
| `gov_dc_moca` | communityaffairs.dc.gov | DC multi-agency grants clearinghouse |

**Why two adapters, not one:**
The two portals are structurally different. learn24 has a single index page with no child detail pages, and its RFA documents are currently hosted externally (Acrobat). communityaffairs.dc.gov has a two-level hierarchy (index → publication pages → attachments). A shared adapter base would require conditionals that obscure both paths; separating them keeps each adapter legible and independently testable.

**Why NOT `gov_dc_learn24 + gov_dc_opgs`:**
`opgs.dc.gov` is defunct. The correct pairing is `gov_dc_ost` (the funder entity) and `gov_dc_moca` (the portal entity). This naming is consistent with the spec's intent: entity-scoped names for single-funder sources, portal-scoped for multi-funder clearinghouses.

**Why NOT `gov_dc_opgs` at all:**
The "OPGS" entity described in the prompt does not have a live grants portal. Do not create an adapter for it.

**What this slice does NOT cover:**
- `gov_dc_osse` (osse.dc.gov — separate future adapter; OSSE grants through learn24 or MOCA are captured as a side effect of these two adapters)
- `gov_dc_dpr` (dpr.dc.gov — out of scope for this slice)
- Other DC agencies posting on communityaffairs.dc.gov that have their own portals

---

## 3. Adapter shape

Both adapters conform to `BaseAdapter`. Both are **Tier B** (semi-structured HTML, static pages, no JS). Plain `httpx` is sufficient — no Playwright.

### 3.1 gov_dc_ost

**Fetch topology:**
```
Pass 1: GET learn24.dc.gov/page/ost-office-grants → store as RawRecord → scan for native PDF links
         GET learn24.dc.gov/page/funding-opportunities-0 → store as RawRecord → scan for native PDF links
Pass 2: For each discovered learn24.dc.gov/sites/default/files/*.pdf → store as RawRecord (secondary)
```

**Discovery rule:** Regex scan of raw HTML bytes for `href` values matching `learn24\.dc\.gov/sites/default/files/.*\.pdf`. No CSS selectors. No XPath. If a href matches this pattern, queue it for Pass 2. All other hrefs (Acrobat, SharePoint, YouTube, external) are silently skipped.

**OPPORTUNITY_SEEN payload per index page:**
```python
{
    "source_id": "gov_dc_ost",
    "external_id": "gov_dc_ost:<page_url>",
    "title": <extracted from <title> tag — regex strip " | learn24" suffix>,
    "funder_name_raw": "DC Office of Out of School Time Grants and Youth Outcomes",
    "extra_content_shas": [sha for each native PDF fetched from this page],
}
```

The index page HTML is the primary raw record. Native PDFs are secondary raw records linked via `extra_content_shas`. No OPPORTUNITY_SEEN per individual PDF — each index page is the unit.

**Why skip Adobe Acrobat links:** The FY27 RFAs are currently published as Acrobat shared documents (`acrobat.adobe.com/id/urn:aaid:sc:...`). These are ephemeral: they break when the OST Office expires the share. They are not archivable via robots-compliant HTTP fetch. The adapter must not follow them. This is a known gap — the actual RFA PDFs for the current cycle are not capturable from the public web without a user-side copy.

**Implementation class:**
```python
class DCOSTAdapter(BaseAdapter):
    source_id = "gov_dc_ost"
    version = "0.1.0"
    rate_limit_per_sec = 0.1  # Crawl-delay: 10 per robots.txt

    _INDEX_URLS = [
        "https://learn24.dc.gov/page/ost-office-grants",
        "https://learn24.dc.gov/page/funding-opportunities-0",
    ]
    _NATIVE_PDF_PATTERN = re.compile(
        r'href=["\']((https?://learn24\.dc\.gov)?/sites/default/files/[^"\']+\.pdf)["\']',
        re.I,
    )
    _PDF_SIZE_CAP = 50 * 1024 * 1024

    def iter_fetch_tasks(self):
        for url in self._INDEX_URLS:
            yield FetchTask(url=url, expected_mime="text/html")

    def parse(self, raw: RawRecord) -> list:
        # Tier B: scan raw bytes for native PDF links, queue them, emit OPPORTUNITY_SEEN
        body = self.store.get(raw.content_sha)
        title = _extract_title(body, suffix=" | learn24")
        pdf_urls = self._NATIVE_PDF_PATTERN.findall(body.decode("utf-8", errors="ignore"))
        for url, _ in pdf_urls:
            if not url.startswith("http"):
                url = "https://learn24.dc.gov" + url
            self._pdf_queue.append({"url": url, "index_sha": raw.content_sha})
        return [(CorpusEventType.OPPORTUNITY_SEEN, {
            "source_id": self.source_id,
            "external_id": f"gov_dc_ost:{raw.fetch_url}",
            "title": title,
            "funder_name_raw": "DC Office of Out of School Time Grants and Youth Outcomes",
            "content_sha": raw.content_sha,
        })]

    def run(self, **kwargs) -> AdapterRunResult:
        result = super().run(**kwargs)
        # Pass 2: fetch queued native PDFs
        with httpx.Client(follow_redirects=True, headers=_DEFAULT_HEADERS) as client:
            for item in self._pdf_queue:
                self._fetch_pdf(item, client, result)
        return result
```

### 3.2 gov_dc_moca

**Fetch topology:**
```
Pass 1: GET communityaffairs.dc.gov/content/community-grant-program → discover /publication/* links
Pass 2: For each /publication/* link → fetch page → emit OPPORTUNITY_SEEN → discover attachment links
Pass 3: For each attachment (communityaffairs.dc.gov/sites/moca/files/*.pdf or .docx) → store as secondary RawRecord
```

**Discovery rules:**
- From index: regex scan for `href` values matching `/publication/[^"']+` (relative or absolute on same domain).
- From publication pages: regex scan for `href` values matching `communityaffairs\.dc\.gov/sites/moca/files/[^"']+\.(pdf|docx)`.
- External links (ZoomGrants, Box, Acrobat, SharePoint) are NOT fetched.

**OPPORTUNITY_SEEN payload per publication page:**
```python
{
    "source_id": "gov_dc_moca",
    "external_id": "gov_dc_moca:<publication_url>",
    "title": <extracted from <title> tag — strip " | Mayors Office of Community Affairs" suffix>,
    "funder_name_raw": "DC Mayor's Office of Community Affairs",
    "content_sha": <publication_page_sha>,
    "extra_content_shas": [sha for each attachment fetched],
}
```

Note: `funder_name_raw` is set to the clearinghouse name ("DC Mayor's Office of Community Affairs") at ingest. The actual issuing agency (OSSE, DOES, DHS, etc.) is embedded in the NOFA title and body — Component 2 resolves this to the correct Funder row.

**Three-pass run() pattern:**
```python
def run(self, **kwargs) -> AdapterRunResult:
    # Pass 1: index page
    result = super().run(**kwargs)
    # Pass 2: publication pages (populated by parse() on the index raw record)
    with httpx.Client(...) as client:
        for pub_url in self._publication_queue:
            self._fetch_publication(pub_url, client, result)
    # Pass 3: attachments (populated by _fetch_publication)
    with httpx.Client(...) as client:
        for item in self._attachment_queue:
            self._fetch_attachment(item, client, result)
    return result
```

**Title extraction helper (shared between both adapters):**
```python
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)

def _extract_title(body: bytes, suffix: str = "") -> str:
    m = _TITLE_RE.search(body.decode("utf-8", errors="ignore"))
    if not m:
        return ""
    title = html.unescape(m.group(1)).strip()
    if suffix and title.endswith(suffix):
        title = title[: -len(suffix)].strip()
    return title
```

This is a single regex on raw bytes — not a CSS selector or XPath. Defensible under the Tier B/C no-selectors rule.

---

## 4. Source register entries

Add to the spec's section 5 gov_* table:

| ID | Source | Tier | Cadence | Adapter style |
|----|--------|------|---------|---------------|
| `gov_dc_ost` | DC OST Office (learn24.dc.gov) | B | Weekly | Two-pass: index fetch + native PDF fetch |
| `gov_dc_moca` | DC MOCA grants clearinghouse (communityaffairs.dc.gov) | B | Weekly | Three-pass: index → publication pages → attachments |

**Retire from spec:** `gov_dc_opportunities` (listed as `opportunities.dc.gov`) — the domain is dead (connection refused). `gov_dc_moca` supersedes it. Note this in the spec update.

---

## 5. Funder auto-create policy

DC government agencies are a known, bounded set. Auto-create on first sighting with `funder_type=govt_local`.

**gov_dc_ost:** One funder, hardcoded at adapter level:
- `canonical_name` = "DC Office of Out of School Time Grants and Youth Outcomes"
- `funder_type` = `govt_local`
- `notes['parent_agency']` = "Deputy Mayor for Education"

**gov_dc_moca:** One funder for the clearinghouse at ingest time:
- `canonical_name` = "DC Mayor's Office of Community Affairs"
- `funder_type` = `govt_local`

The issuing agency per NOFA (OSSE, DOES, DHS, DHCD, DMPSJ, etc.) is deferred to Component 2's entity resolution pass. Component 2 reads the NOFA title and PDF body, identifies the issuing agency name, and updates `funder_name_raw` → resolves to a more specific `Funder` row. The MOCA row remains as a "publisher" funder and the issuing agency becomes the "grantmaker" funder. How this dual-funder relationship is modeled is an open question for Chris (see §12).

---

## 6. OpportunityInstance fields produced at ingest

Per Tier B/C principle and the slice 3 scope: title + funder_name_raw + source URL + raw record only. All other fields deferred to Component 2.

| Field | gov_dc_ost | gov_dc_moca |
|-------|------------|-------------|
| `title` | From `<title>` tag, suffix-stripped | From `<title>` tag, suffix-stripped |
| `funder_name_raw` | Hardcoded: "DC Office of Out of School Time Grants and Youth Outcomes" | Hardcoded: "DC Mayor's Office of Community Affairs" |
| `source_id` | "gov_dc_ost" | "gov_dc_moca" |
| `external_id` | "gov_dc_ost:{page_url}" | "gov_dc_moca:{publication_url}" |
| `first_seen_at` | `fetched_at` | `fetched_at` |
| All other fields | `None` / deferred | `None` / deferred |

---

## 7. PDF and attachment handling

Both adapters mirror the grants_gov pattern from slice 2:

- HEAD request first to check `Content-Length` (50 MB hard cap).
- If HEAD omits Content-Length, proceed with GET and abort if download exceeds 50 MB.
- Store content-addressed as a separate `RawRecord`.
- Link to the parent opportunity via `extra_content_shas` in the OPPORTUNITY_SEEN event.
- Emit a second OPPORTUNITY_SEEN event (linking parent sha + attachment sha) so the materializer can M2M-link them.

**gov_dc_ost PDF sources:** Only `learn24.dc.gov/sites/default/files/*.pdf`. Do not fetch Adobe Acrobat links.

**gov_dc_moca attachment sources:** `communityaffairs.dc.gov/sites/moca/files/**/*.pdf` and `.docx`. Docx files should be stored as raw bytes with MIME type `application/vnd.openxmlformats-officedocument.wordprocessingml.document`. Do not fetch ZoomGrants, Box, or other external application-portal links.

---

## 8. Pre-filtering at ingest

**gov_dc_ost:** No pre-filtering. The learn24 portal is OST-focused by definition. The Youth Scholarships CE Program is org-facing (organizations administer scholarships, not families applying directly), so it is in scope. No family-facing content appears on this portal.

**gov_dc_moca:** No pre-filtering at ingest. The clearinghouse publishes ~22 active NOFAs across all DC agencies, with only ~6–8 directly relevant to our CBO segment. However, per the Tier B/C principle, raw bytes are stored regardless of downstream relevance. The content-addressed store and the 50 MB cap are the only gates. Component 2's relevance classifier (not yet built) handles downstream filtering. If the unfiltered volume becomes operationally noisy, a keyword-based pre-filter on NOFA title could be added as a configurable `title_deny_patterns` list in the adapter — but this is not recommended for V1.

---

## 9. Cadence

| Source | Recommended cadence | Rationale |
|--------|--------------------|-----------|
| `gov_dc_ost` | Weekly | OST Office opens one grant cycle per fiscal year; RFAs are posted months in advance. Sub-week granularity adds no value. |
| `gov_dc_moca` | Weekly | MOCA publishes NOFAs as they arise but not with sub-week frequency. Weekly is sufficient. The spec lists DC agencies as "Daily" but that is unnecessarily aggressive for these two static-HTML portals. |

Both portals have `Crawl-delay: 10` in robots.txt. The adapters must respect this via `rate_limit_per_sec = 0.1` (1 request per 10 seconds). With ~22 publication pages + ~22 attachments on the gov_dc_moca side, a full run takes roughly 7–8 minutes. Acceptable for a weekly scheduled job.

---

## 10. Test fixtures plan

Mirror slice 2's synthetic fixture pattern. No real DC government HTML or PDFs in the test suite.

### gov_dc_ost fixtures

| Fixture | Description | What it tests |
|---------|-------------|---------------|
| `ost_index.html` | Synthetic learn24 index page with 2 native PDF links + 2 Acrobat links | Discovers 2 native PDFs, skips 2 Acrobat links |
| `ost_supporting.pdf` | Minimal valid PDF (5 KB) | Secondary RawRecord stored, linked via extra_content_shas |
| `ost_index_no_pdfs.html` | Index page with only Acrobat links | No secondary fetch, still emits OPPORTUNITY_SEEN for the page |
| `robots.txt` | Synthetic permissive robots.txt | `ROBOTS_BLOCKED` event when path disallowed (use a disallow rule to test) |

Test cases:
1. Index page → discovers 2 native PDF links → queues both
2. Native PDF fetched → stored as RawRecord, linked via extra_content_shas
3. Acrobat link present → silently ignored, not queued
4. Two runs of same fixture → idempotent (same sha, no second RawRecord)
5. PDF > 50 MB → skipped with `OPPORTUNITY_FILTERED` event
6. robots.txt blocks the index path → `ROBOTS_BLOCKED` event, no OPPORTUNITY_SEEN

### gov_dc_moca fixtures

| Fixture | Description | What it tests |
|---------|-------------|---------------|
| `moca_index.html` | Synthetic community-grant-program page with 3 /publication/ links + 1 external link | Discovers 3 pub pages, skips 1 external |
| `moca_pub_1.html` | Synthetic publication page with 2 native PDF attachments | Emits OPPORTUNITY_SEEN, queues 2 PDFs |
| `moca_pub_2.html` | Synthetic publication page with 1 DOCX attachment | DOCX stored with correct MIME type |
| `moca_pub_3.html` | Synthetic publication page with no attachments | OPPORTUNITY_SEEN emitted, no attachment fetch |
| `moca_attachment.pdf` | Minimal valid PDF | Secondary RawRecord linked |
| `moca_attachment.docx` | Minimal valid DOCX (OpenXML format, ~1KB) | Secondary RawRecord with correct MIME |

Test cases:
1. Index page → discovers 3 publication URLs, skips 1 external link
2. Publication page → OPPORTUNITY_SEEN emitted with correct title (suffix stripped)
3. Publication page with 2 attachments → 2 secondary RawRecords, both in extra_content_shas
4. Publication page with no attachments → OPPORTUNITY_SEEN with empty extra_content_shas
5. DOCX attachment → stored with correct MIME type
6. Idempotency: same publication URL fetched twice → same sha, no duplicate RawRecord
7. robots.txt blocked publication path → ROBOTS_BLOCKED, no OPPORTUNITY_SEEN for that publication

---

## 11. Commit breakdown

Estimated 5–6 commits for one Sonnet implementation session:

| # | Commit | Contents |
|---|--------|----------|
| 1 | `feat(grants_ingest): gov_dc_ost adapter — index fetch + native PDF discovery` | `adapters/dc_ost.py`, `_extract_title` helper in `adapters/http.py` or a new `adapters/html_util.py` |
| 2 | `test(grants_ingest): gov_dc_ost adapter — 6 test cases` | `tests/grants_ingest/fixtures/dc_ost/` + `tests/grants_ingest/test_dc_ost_adapter.py` |
| 3 | `feat(grants_ingest): gov_dc_moca adapter — three-pass index/publication/attachment fetch` | `adapters/dc_moca.py` |
| 4 | `test(grants_ingest): gov_dc_moca adapter — 7 test cases` | `tests/grants_ingest/fixtures/dc_moca/` + `tests/grants_ingest/test_dc_moca_adapter.py` |
| 5 | `feat(grants_ingest): wire gov_dc_ost + gov_dc_moca into ingest_run` | `management/commands/ingest_run.py` — add to `_build_adapter()` factory |
| 6 | `docs(grants_ingest): slice-3a plan + spec source register update` | This plan file, `docs/specs/grant_ingestion.md` section 5 (retire gov_dc_opportunities, add gov_dc_ost and gov_dc_moca rows) |

If the `_extract_title` helper is shared between adapters, extract it into `adapters/html_util.py` in commit 1 and import it in commit 3. Do not duplicate it.

---

## 12. Open questions for Chris

**Q1 — Dual-funder model for gov_dc_moca:**
MOCA is the publisher; the issuing agency (OSSE, DOES, etc.) is the actual grantmaker. At ingest we set `funder_name_raw = "DC Mayor's Office of Community Affairs"`. Component 2 would need to identify the issuing agency from the NOFA title or body and create a second Funder row. Should the OPPORTUNITY_SEEN payload carry both (a clearinghouse funder and an issuing-agency hint)? Or is one `funder_name_raw` per event correct and the dual-funder resolution is entirely Component 2's problem? If you want the adapter to carry the issuing agency as `notes['issuing_agency_hint']` (extracted from the NOFA title with a simple regex), that's possible without violating the no-CSS-selectors rule.

**Q2 — gov_dc_moca keyword pre-filter:**
~14 of the 22 active NOFAs on communityaffairs.dc.gov are clearly outside scope (electric vehicles, Chinatown lease incentive, HIV housing). Storing all of them as raw records is ~14 noise records per weekly run. The volume is trivial (these pages are small), but the OpportunityInstance table grows with low-relevance rows. Options: (a) store everything, filter downstream (cleanest, consistent with Tier B/C principle), (b) add a configurable `title_deny_patterns` list to skip obviously irrelevant NOFAs at ingest (adds adapter complexity, introduces ingest-time policy that belongs downstream). Recommend (a), but wanted to surface the trade-off.

**Q3 — DC DPR partner-programming grants:**
DC Parks and Recreation (dpr.dc.gov) runs community partnership grants separate from MOCA. A few DPR grants may appear on communityaffairs.dc.gov as NOFAs (the survey showed none currently), but the bulk of DPR partner programming lives on dpr.dc.gov. Should `gov_dc_dpr` be its own slice 3 adapter (separate adapter, separate commit chain), or defer it entirely to a future phase? The spec section 5 lists it, but it's not OST-focused enough to be in the top-priority set.

**Q4 — Adobe Acrobat RFAs:**
The live FY27 OST program-specific RFAs (the actual application instructions) are currently hosted as Adobe Acrobat shared documents, not on learn24.dc.gov. This means the adapter will NOT capture them. The index page HTML (stored as a RawRecord) contains the program descriptions, dates, and Cityspan application instructions, but not the full RFA PDF content. Is this an acceptable coverage gap for V1, or should we attempt to fetch the Acrobat links (noting they will break unpredictably)?

**Q5 — `gov_dc_ost` external_id per index page or per discovered program:**
The adapter currently emits one OPPORTUNITY_SEEN per index page URL (covering all 7 grant programs collectively). An alternative is to emit one per program by parsing the page's `<h2>` anchors (which list each program name). The first approach is simpler and avoids any per-page layout assumption; the second produces more useful OpportunityInstance rows pre-extraction. This is a design-space choice — recommend the first (one per index page) for V1, but wanted your input.

---

## 13. Out of scope for this slice

- Non-DC government sources (slice 3 adapters 2–5 cover MD and VA)
- DC private foundations (`pf_*` — a separate slice)
- `gov_dc_osse` (osse.dc.gov direct adapter — separate future slice; OSSE grants visible through MOCA and learn24 are a side-effect of these adapters)
- `gov_dc_dpr` (see Q3 above)
- PDF content parsing or any field extraction from stored PDFs
- LLM extraction pass
- State-transition state machine
- Relevance ranking or filtering for the donor surface
- `find_grants` CLI changes (the existing command will automatically surface new OpportunityInstance rows once the materializer runs)
- Railway cron wiring
- Any changes to the existing adapter suite (irs_990pf, propublica_np, grants_gov, pnd_rfp)

---

## 14. Architectural note: spec corrections to make

Before implementation, update `docs/specs/grant_ingestion.md` section 5:

1. Remove or annotate `gov_dc_opportunities` — `opportunities.dc.gov` is dead (connection refused 2026-05-23).
2. Remove or annotate the CYITC reference — "DC Children and Youth Investment Trust (CYITC)" is listed as "defunct but archived RFPs informative" in the spec. Under DC Law 21-261, the OST Office superseded CYITC in 2017. The CYITC URLs (`cyitc.org`, `dctrust.org`) should not be followed. The OST Office's FY21–FY24 archive on learn24 covers the relevant historical period.
3. Add `gov_dc_ost` and `gov_dc_moca` rows to the source register table.
4. Note that `opgs.dc.gov` redirects to ServesDC, not a grants portal — it is not a viable source.
