# Grant Ingestion Spec — Component 1

**Project:** Understory Commons
**Scope:** Source-by-source ingestion specs for grant discovery corpus
**Status:** Draft, intended as input to Claude Code

## Purpose

This spec defines what to pull, how to pull it, and what to extract for each
source feeding the Understory Commons grant corpus. It is the implementation
guide for Component 1 (ingestion + corpus versioning) of the grant discovery
system.

The output of ingestion is a versioned corpus of raw documents plus a layer of
normalized records keyed against the unified schema below. Downstream
extraction, retrieval, and ranking components consume the normalized records;
they never touch source-specific code.

## Principles

Three things to internalize before writing any scraper:

1. **Raw bytes are immutable and content-addressed.** Every fetched document
   lands in the object store under `sha256(content)` before anything else
   happens. Parsing, extraction, and normalization are downstream layers that
   read from the object store, never from the live source.

2. **Identity is two-layered and soft.** Program identity
   (funder + canonical program name) and opportunity instance identity
   (program + cycle/window) are tentative at ingest. Entity resolution may
   revise them. Every revision is a logged event.

3. **Source-specific code stops at the boundary.** Each source produces
   `RawRecord` objects and a candidate `OpportunityInstance`. It does not own
   the schema, the deduplication logic, or the funder/program registry.

4. **Tier A is parsed at ingest; Tier B/C is not.** Structured sources
   (XML, JSON APIs, RSS) yield typed fields directly — there is no parsing
   freedom to defer, and the field maps in this spec describe what ingest
   produces. Unstructured sources (HTML pages, PDFs) are ingested as raw
   bytes only; all field extraction is Component 2's responsibility, using
   models versioned and evaluated independently of source code. The
   per-source field tables for Tier B/C sources describe what Component 2
   should produce from the raw record — they are not specifications of
   ingest-time behavior. No CSS selectors, XPath expressions, or per-page
   layout assumptions appear in adapter code for Tier B/C sources.

## Unified target schema

This is the recap of what every source feeds. Defined fully in the schema spec;
summarized here so the source specs can reference field names.

```python
class RawRecord:
    content_sha: str            # primary key, sha256 of raw bytes
    fetch_url: str
    fetched_at: datetime
    source_id: str              # which adapter produced this
    mime_type: str
    content_ref: str            # object store URI
    http_status: int
    fetch_metadata: dict        # headers, redirects, robots state, etc.

class OpportunityInstance:
    id: UUID
    program_id: Optional[UUID]              # null until resolved
    funder_id: Optional[UUID]               # null until resolved
    title: str
    application_open_at: Optional[datetime]
    application_close_at: Optional[datetime]
    rolling: bool
    award_min: Optional[Decimal]
    award_max: Optional[Decimal]
    typical_award: Optional[Decimal]
    total_pool: Optional[Decimal]
    program_type: ProgramType               # project / capacity / operating / scholarship / capital
    eligibility: EligibilityStruct          # typed, drives hard-constraint filter
    geographic_scope: GeoScope
    subject_areas: list[str]
    status: OpportunityStatus               # open/upcoming/closed/rolling/unreachable/provisionally_withdrawn/withdrawn
    first_seen_at: datetime
    last_seen_at: datetime
    source_records: list[str]               # content_shas
    extraction_model_version: str
    schema_version: str
    provenance: ExtractionTrace

class Funder:
    id: UUID
    ein: Optional[str]
    canonical_name: str
    aliases: list[str]
    funder_type: FunderType                 # private_foundation / community_foundation / public_charity / govt_federal / govt_state / govt_local / corporate / united_way
    accepts_unsolicited: Optional[bool]
    typical_award_range: Optional[tuple[Decimal, Decimal]]
    historical_recipients: list[UUID]       # populated from 990-PF
    notes: dict

class Program:
    id: UUID
    funder_id: UUID
    canonical_name: str
    aliases: list[str]
    historical_instances: list[UUID]
    accumulated_eligibility: Optional[EligibilityStruct] = None
    # ^ Deferred. Populated by a separate inference component, not by
    # ingest. The aggregation method (union / majority / most-recent /
    # learned) is undecided and out of scope for Component 1.
```

`EligibilityStruct` is the part that drives Component 3 (hard-constraint filter)
and is the most consequential to get right. Fields: `org_type` (501c3,
fiscal_sponsor_ok, govt, etc.), `geo_required` (list of FIPS/state/county),
`geo_excluded`, `budget_range_required`, `years_in_operation_min`,
`recipient_population_focus` (youth-ed, OST, etc.), `award_purpose_allowed`
(operating, project, capital, scholarship), `prior_grantee_restriction`,
`match_requirement`, `application_route` (open/RFP/invitation/LOI-first).

## Source register

Sources are tiered by structural quality of their data:

- **Tier A (structured):** API or XML with typed fields. Cheap to ingest,
  high signal.
- **Tier B (semi-structured):** Consistent HTML pages with stable layout, or
  third-party aggregator portals (Submittable, Foundant) with regular DOM.
- **Tier C (unstructured):** Bespoke HTML per page, PDFs, mixed content.
  Expensive, requires per-source extractor.

| ID | Source | Tier | Cadence | Adapter style |
|----|--------|------|---------|---------------|
| `irs_990pf` | IRS 990-PF filings | A | Quarterly | Batch XML downloader |
| `propublica_np` | ProPublica Nonprofit Explorer | A | Weekly | REST API |
| `cf_gwcf` | Greater Washington CF | B/C | Weekly | Per-portal scraper |
| `cf_cfnova` | Community Foundation for Northern VA | B/C | Weekly | Per-portal scraper |
| `cf_arlcf` | Arlington Community Foundation | B/C | Weekly | Per-portal scraper |
| `cf_cfmoco` | Montgomery County CF | B/C | Weekly | Per-portal scraper |
| `cf_pgcf` | Prince George's CF | B/C | Weekly | Per-portal scraper |
| `cf_*` | Other DMV community foundations | B/C | Weekly | Per-portal scraper |
| `pf_*` | DMV private foundations (~50) | C | Weekly | Config-driven, per-foundation |
| `gov_dc_osse`, `gov_dc_dpr`, `gov_dc_opportunities` | DC agencies | B/C | Daily | Per-portal scraper |
| `gov_md_msde`, `gov_md_mococcyf`, `gov_md_pgocfys` | MD agencies + counties | B/C | Daily | Per-portal scraper |
| `gov_va_doe`, `gov_va_ffx_ccfp`, `gov_va_arl`, `gov_va_alx`, `gov_va_loudoun` | VA agencies + counties | B/C | Daily | Per-portal scraper |
| `uwnca` | United Way NCA | B/C | Weekly | Per-portal scraper |
| `pnd_rfp` | Philanthropy News Digest RFPs | A | Daily | RSS + page fetch |
| `submittable` | Submittable discover | B | Weekly | Filtered listing scraper |
| `projectstream`, `foundant` | Other aggregators | B | Weekly | Filtered listing scraper |
| `grants_gov` | grants.gov | A | Daily | XML extract + REST |
| `wayback_*` | Internet Archive Wayback Machine | B | On-demand + monthly sweep | CDX API + page fetch |

URLs in the per-source sections below should be verified by the implementer
before coding — some change without redirects.

---

## 1. IRS 990-PF filings (`irs_990pf`)

### What and why

Annual tax returns filed by private foundations. Part XV-1 lists every grant
paid in the tax year: recipient name, address, EIN (sometimes), purpose, amount.
Part XV-2 describes the foundation's application process, geographic
restrictions, and program areas in the foundation's own words.

This is the **only source that gives ground truth on who won what from whom.**
We don't use it for live grant discovery (it lags 6-18 months). We use it for:

- Building the funder registry with verified EINs, addresses, asset sizes.
- Extracting foundation-level eligibility (geographic priorities, focus areas)
  from Part XV-2.
- Populating the supervised signal needed by Component 6
  (outcome-conditioned ranking).
- Cross-referencing recipients to validate that a foundation actually funds the
  segment we claim it does.

Ingest this early, even though the downstream consumer doesn't exist yet.

### Access

The IRS publishes 990 data as XML. Historically distributed via AWS Open Data
(`irs-form-990` S3 bucket); the active location should be verified before
implementing — IRS bulk data access has shifted in recent years. ProPublica's
Nonprofit Explorer API wraps the same data and is the easier path for
per-organization queries.

- **ProPublica API base:** `https://projects.propublica.org/nonprofits/api/v2/`
- **Organization endpoint:** `/organizations/{ein}.json` returns filings index.
- **Search endpoint:** `/search.json?q=&state[id]=DC&ntee[id]=B`
- **IRS bulk:** XML zip files by tax year.

Both are free, no auth. Rate-limit yourself to 1 req/sec on ProPublica.

### Update cadence

Quarterly is fine. New filings trickle in continuously but there's no urgency.

### Fields to extract

| Source field (990-PF / API) | Unified schema field | Notes |
|---|---|---|
| Filer EIN | `Funder.ein` | Primary funder key. |
| Filer name | `Funder.canonical_name` | After normalization (strip "Inc", "Foundation" suffix variants). |
| Filer address | `Funder.notes['address']` | Use for DMV-geographic filtering. |
| Tax year | (filing metadata) | Tag each grant row with this. |
| `TotalGrantOrContributionPdDurYrAmt` | `Funder.notes['annual_grants_paid'][year]` | Annual giving size. |
| Part XV-1 recipient name | (recipient-side, links into Funder graph) | Resolves against IRS BMF for EIN. |
| Part XV-1 recipient address | (recipient-side) | Helps EIN matching. |
| Part XV-1 grant purpose | (raw text, stored on the historical-grant edge) | Free-form; train an extractor on it later. |
| Part XV-1 grant amount | (numeric, on the historical-grant edge) | |
| Part XV-1 relationship | (flag) | Donor-advised, scholarship, etc. |
| Part XV-2 application info text | `Funder.notes['application_info_text']` | Source for `accepts_unsolicited`, geographic scope, deadlines. |
| Part XV-2 restrictions | `Funder.notes['restrictions_text']` | Same. |
| Part XV-2 limitations on awards | `Funder.notes['award_limitations_text']` | Same. |

Build a parallel `HistoricalGrant` table from Part XV-1:

```python
class HistoricalGrant:
    funder_id: UUID
    funder_ein: str
    tax_year: int
    recipient_name_raw: str
    recipient_address_raw: str
    recipient_ein: Optional[str]
    recipient_id: Optional[UUID]    # resolved against IRS BMF / our org registry
    amount: Decimal
    purpose: str
    relationship_flag: Optional[str]
    source_record_sha: str
```

This is the table that becomes training data for outcome ranking.

### Normalization

- Recipient EIN resolution: many small recipients lack EINs in the filing.
  Resolve against the IRS BMF (Business Master File, public download) using
  fuzzy name + address match. Keep `recipient_id` nullable; fill in over time.
- Purpose strings have no schema. Don't try to classify them at ingest; store
  raw, classify in a separate batch job once we have a taxonomy.
- Multi-year commitments sometimes appear as one large grant in year 1 and
  sometimes as annual installments. Note this in the `relationship_flag`.

### Gotchas

- Pre-2012 filings may be image-only PDFs. Ignore them initially; the value is
  in the last 5-10 years anyway.
- 990-PF is private foundations only. Community foundations file 990 and
  report grants in Schedule I (similar structure, different form). Treat as a
  separate parser.
- Filing extensions are common. Don't assume last-fiscal-year data is complete
  until 18 months out.
- EIN format is "XX-XXXXXXX" in some sources, "XXXXXXXXX" in others. Normalize
  to digits-only internally.

---

## 2. ProPublica Nonprofit Explorer (`propublica_np`)

### What and why

REST API over IRS 990 data plus IRS BMF. Primary use case: looking up a single
org by EIN to get current filings index, NTEE code, and basic metadata.
Complements `irs_990pf` (which is bulk) by serving lookups during ingestion.

### Access

- `GET /organizations/{ein}.json` — filings index for one org.
- `GET /search.json?q=&state[id]=&ntee[id]=` — org search.
- Free, public, rate-limited politely.

### Fields to extract

| Source field | Unified schema field | Notes |
|---|---|---|
| `ein` | `Funder.ein` | |
| `name` | `Funder.canonical_name` | |
| `subseccd` (subsection code) | `Funder.notes['irs_subsection']` | 501c3 = 3, private foundation = (varies). |
| `ntee_code` | `Funder.notes['ntee']` | B = education, B90 = ed services, O = youth dev. |
| `address`, `city`, `state`, `zipcode` | `Funder.notes['address']` | |
| `tax_period`, `revenue_amount` | `Funder.notes['annual_revenue'][year]` | |
| Filings list (`filings_with_data`) | (used to drive 990-PF fetch) | Each entry has a PDF URL and an XML URL. |

NTEE codes are the cheap pre-filter for "is this a funder we care about." Codes
starting with B, O, P-30, P-32, P-33, T are the youth-ed-adjacent set.

### Gotchas

- The API returns "the latest known filing"; for historicals, pull each
  filing's XML separately.
- Some private foundations file 990 (not 990-PF) — depends on their
  classification. Don't assume.

---

## 3. Community foundation portals (`cf_*`)

### What and why

Community foundations host dozens of donor-advised funds and run their own
strategic initiatives. They publish open RFPs on their websites and often use
Foundant or Submittable as their application backend. They aggregate funders
who would never be discoverable individually.

Each foundation gets its own adapter. They share a common scraping pattern but
diverge enough in layout that one-size-fits-all extraction will miss things.

### Target portals (DMV, initial set)

| ID | Foundation | Site (verify before coding) |
|---|---|---|
| `cf_gwcf` | Greater Washington Community Foundation | thecommunityfoundation.org |
| `cf_cfnova` | Community Foundation for Northern Virginia | cfnova.org |
| `cf_arlcf` | Arlington Community Foundation | arlcf.org |
| `cf_cfmoco` | Montgomery County Community Foundation | cfmoco.org |
| `cf_pgcf` | Prince George's Community Foundation | pgcommunityfoundation.org |
| `cf_cfloudoun` | CF for Loudoun and Northern Fauquier | communityfoundationlf.org |
| `cf_cffredco` | CF of Frederick County | cffredco.org |
| `cf_cfar` | CF of the Rappahannock River Region | (verify) |
| `cf_cfacc` | CF Alexandria | (verify) |

### Access

Web scraping. Maintain a per-foundation config that controls *fetching only* —
not parsing:

```yaml
cf_gwcf:
  base_url: https://www.thecommunityfoundation.org
  index_paths:
    - /grants/open-opportunities
    - /grants/active-funds
  pagination: none           # or a discovery rule for finding next-page URLs
  detail_link_discovery: "all anchors under main; filter by URL pattern"
  render: static             # static | js
  fetch_rate_limit: 1 req/3s
  robots_compliance: strict
```

The adapter's job is to (a) discover detail URLs from the index pages and
(b) fetch each detail page's full HTML (rendered if `render: js`) and any
linked PDFs into the raw object store. That is the entire output of ingest
for this source. There are no CSS selectors, no field-level extractors, no
schema-aware code in the adapter.

For pages requiring JavaScript, the adapter uses Playwright; for static
pages, plain `httpx`. The `render` flag drives the choice.

Detail-link discovery is intentionally loose ("anchors under main, filter
by URL pattern") rather than precise selectors. Loose discovery occasionally
captures non-grant pages; that's cheaper than the brittleness of precise
selectors.

### Fields Component 2 should extract from these raw records

Ingest produces raw HTML and PDF only. The table below describes what
Component 2's extractor must produce from those records. It is reference
material for the extractor's evaluation harness, not for ingest code.

| Page field (typical) | Unified schema field |
|---|---|
| Title | `OpportunityInstance.title` |
| Funder name (parent CF and named fund) | `OpportunityInstance.funder_id` (resolves to parent CF); fund name → `Program.canonical_name` |
| Deadline / close date | `application_close_at` |
| LOI deadline (if separate) | (multi-stage, see below) |
| Open date | `application_open_at` |
| Award range / typical award | `award_min`, `award_max`, `typical_award` |
| Total pool | `total_pool` |
| Geographic eligibility | `eligibility.geo_required` |
| Org type requirements | `eligibility.org_type` |
| Focus areas | `subject_areas` |
| Population served | `eligibility.recipient_population_focus` |
| Application URL / portal | `OpportunityInstance.notes['apply_url']` |
| Contact | `OpportunityInstance.notes['contact']` |
| Full text | (preserved in raw record; powers retrieval) |

### Multi-stage applications

Many CF programs have LOI → invited proposal flow. Model as one
`OpportunityInstance` with two date fields: `loi_close_at` and
`full_proposal_close_at` (extend the schema). Don't fork into two instances.

### Normalization

- Single page often lists multiple programs. The detail-extraction config
  should produce one record per `<section>` or `<article>` block, not one per
  page.
- "By invitation only" programs should be flagged via
  `eligibility.application_route = 'invitation'` and surfaced separately
  downstream (users may still want to know about them as networking targets).

### Gotchas

- Programs vanish from the site after their deadline. Use the Wayback Machine
  as a backfill source: monthly snapshot fetches let you reconstruct the
  off-cycle calendar.
- Donor-advised funds sometimes show up as funders even though they're not
  open to applications. Distinguish "fund exists" from "fund accepts apps."

---

## 4. DMV private foundations, direct scraping (`pf_*`)

### What and why

The bulk of money funding 10-50 student DMV CBOs comes from private
foundations that have their own websites with their own application
instructions. Each is high signal (a few opportunities per year), low volume,
and idiosyncratic.

Target ~50 foundations. Maintain the list as a YAML config in the repo,
versioned. Each foundation has an adapter or a generic-scraper config.

### Starter list (build the YAML against this — verify each)

Morris and Gwendolyn Cafritz Foundation, Eugene and Agnes E. Meyer Foundation,
Marpat Foundation, Public Welfare Foundation, England Family Foundation,
Weissberg Foundation, Naomi and Nehemiah Cohen Foundation, Philip L. Graham
Fund, Diane and Norman Bernstein Foundation, Hattie M. Strong Foundation,
Clark-Winchcole Foundation, Venable Foundation, Morningstar Foundation, Bender
Foundation, Lois and Richard England Family Foundation, The Share Fund,
Crimsonbridge Foundation, Consumer Health Foundation, Healthcare Initiative
Foundation, Horning Family Fund, The Summit Fund of Washington, Eagles
Charitable Foundation, Wallace Genetic Foundation, World Bank Group Community
Connections Fund, Northern Virginia Health Foundation, Jack Kent Cooke
Foundation, Public Welfare Foundation, Z. Smith Reynolds (peripheral),
Pearlstone Foundation, Aaron and Lillie Straus Foundation,
Abell Foundation (Baltimore-DMV), France-Merrick Foundation, Harry and Jeanette
Weinberg Foundation (Baltimore-DMV), Schuster Family Foundation,
Stewart R. Mott Foundation, Open Society Foundations DC programs,
Hill-Snowdon Foundation, Surdna Foundation, Wallace Foundation (national but
funds OST), Charles Stewart Mott Foundation, William T. Grant Foundation,
Annie E. Casey Foundation, Robert Wood Johnson Foundation, W.K. Kellogg
Foundation (regional priorities), Walmart Foundation (regional), Bainum Family
Foundation, Greater Washington Community Foundation (covered separately).

Curate to ~50 actually DMV-active. Cross-check by hitting each candidate's
recent 990-PF and confirming DMV recipients.

### Access

Scraping. Each foundation's "how to apply" or "grant opportunities" page is
the entry point. Many don't list opportunities at all — they describe their
funding philosophy and process generally.

Adapters capture full HTML and any linked PDFs as raw records — no field
extraction at ingest, per the Tier B/C parsing-deferral principle. Two
fetch profiles:

- **Static-foundation pages** (most): one or two pages describing program
  areas, geography, application process, deadlines. Re-fetch monthly to catch
  changes.
- **Dynamic-foundation pages** (few): some list specific RFPs with cycles —
  re-fetch weekly.

A per-foundation YAML config drives fetch behavior only (entry URLs, render
mode, rate limit, robots posture). It contains no selectors or field maps.

### Fields Component 2 should extract from these raw records

Ingest produces raw HTML and PDF only. The two tables below describe what
Component 2's extractor must produce from those records — reference for the
extractor's evaluation harness, not for ingest code.

Foundation-level (updates the `Funder` record):

| Field | Unified |
|---|---|
| Foundation name | `Funder.canonical_name` |
| EIN (often in footer/contact) | `Funder.ein` |
| Accepts unsolicited? | `Funder.accepts_unsolicited` |
| Geographic scope | `Funder.notes['geo_scope']` |
| Program areas | `Funder.notes['program_areas']` |
| Typical award size | `Funder.typical_award_range` |
| Application route | `Funder.notes['application_route']` (open / LOI / invitation) |
| Contact | `Funder.notes['contact']` |
| Deadlines | (Program- or instance-level if specific cycles) |

Opportunity-level (if specific RFPs listed): same as `cf_*` table above.

### Normalization (Component 2 guidance)

- The foundation pages are often the ground truth for `accepts_unsolicited` —
  the extractor should trust the page over the 990-PF, since foundations
  sometimes change policy faster than their tax filings reflect.
- Many of these foundations fund "by invitation" or "through staff
  initiative." Flag, but still surface to users; knowing who funds adjacent
  work matters.

### Gotchas

- Expect 20-40% of these sites to change layout per year. Because ingest
  captures raw bytes only, layout changes don't break the adapter —
  Component 2's extractor absorbs the noise. Adapter failure here means the
  page is unreachable, not that parsing failed.
- Some sites block scraping. Respect robots.txt. Some require JS. Some have
  PDFs that contain all the info — the foundation page just links to the PDF.
  The adapter fetches both.

---

## 5. Government portals: state, county, city (`gov_*`)

### What and why

Government grants are often the largest single awards a DMV CBO can win
(21st CCLC pass-throughs in the $50K-$300K range, county youth-services grants
in the $20K-$150K range). They have crisper structure than foundation pages
(RFPs are formal documents) but are scattered across dozens of agency portals.

### Target portals (initial set)

DC:
- DC OSSE (osse.dc.gov) — out-of-school time, 21st CCLC, ELP
- DC DPR (dpr.dc.gov) — programming partnerships
- opportunities.dc.gov — citywide RFP/grant portal
- DC Office of Victim Services and Justice Grants
- DC Children and Youth Investment Trust (CYITC) — defunct but archived RFPs informative

Maryland:
- MSDE (marylandpublicschools.org) — 21st CCLC, Title programs
- Montgomery County Collaboration Council for Children, Youth and Families
  (collaborationcouncil.org)
- Prince George's County Office of Youth and Family Services
- MD State Arts Council
- MD Governor's Office for Children
- eMaryland Marketplace (emarylandmarketplace.com) — procurement, filter to
  grant opportunities

Virginia:
- VA DOE (doe.virginia.gov) — 21st CCLC, Title programs
- Fairfax County Consolidated Community Funding Pool (CCFP) (fairfaxcounty.gov)
- Arlington County DHS — Project Peace, etc.
- Alexandria Children, Youth and Families
- Loudoun County Linking Children to Resources
- eVA (eva.virginia.gov) — VA procurement, filter to grants

### Access

Mix of HTML scraping and PDF parsing. Most agencies post RFPs as PDFs linked
from an HTML index page. The procurement portals (eVA, eMaryland) have search
APIs but require filtering.

### Fields to extract

| RFP field | Unified |
|---|---|
| RFP title | `OpportunityInstance.title` |
| RFP number / solicitation ID | `OpportunityInstance.notes['solicitation_id']` |
| Issuing agency | `Funder.canonical_name` (funder_type=govt_*) |
| Posted date | `OpportunityInstance.first_seen_at` (override with posted date if explicit) |
| Application deadline | `application_close_at` |
| Pre-application / bidder conference | `OpportunityInstance.notes['pre_app']` |
| Award floor / ceiling | `award_min`, `award_max` |
| Total funding available | `total_pool` |
| Number of awards expected | `OpportunityInstance.notes['num_awards']` |
| Performance period | `OpportunityInstance.notes['perf_period']` |
| Match requirement | `eligibility.match_requirement` |
| CFDA / Assistance Listing | `OpportunityInstance.notes['cfda']` |
| Eligible applicants (org type) | `eligibility.org_type` |
| Geographic eligibility | `eligibility.geo_required` |
| Title I target / school designation | `eligibility.recipient_population_focus` |
| Program description (full RFP text) | (raw record, drives retrieval) |
| Attachments | (raw records, separate `content_sha` each) |

### Normalization

- CFDA / Assistance Listing numbers are canonical (e.g. 84.287 = 21st CCLC).
  Maintain a lookup table; tag opportunities by Assistance Listing.
- Government RFPs often have a clear `eligible_applicants` enumeration. Map
  the codes/text to your `org_type` taxonomy at extraction time, not at
  ingest.
- Pass-through programs (21st CCLC funded federally but issued by states) get
  both an Assistance Listing tag and a state-issuance tag.

### Gotchas

- Procurement portals mix grants, contracts, and procurements. The filter is
  non-trivial; some agencies use "grant" and "contract" loosely. Build a
  classifier (rules first, model later) for "is this a grant a CBO could
  apply to."
- PDFs are usually scanned text — OCR rarely needed (most are digital-native)
  but check.
- Government sites have aggressive caching and sometimes return stale
  versions. Compare `Last-Modified` headers across fetches and don't trust
  cache.
- Some agencies post RFPs through PDF email blasts only — listed nowhere
  publicly. Out of scope; users get those through their existing networks.

---

## 6. United Way NCA (`uwnca`)

### What and why

UWNCA distributes Community Impact Grants and runs a few targeted initiatives.
Worth pulling because it's a significant funder for the segment and its
strategic priorities propagate to other DMV funders.

### Access

`unitedwaynca.org` — scrape. Some cycles managed through Submittable.

### Fields

Standard `OpportunityInstance` schema. Capture UWNCA's "impact area"
classification — it's a useful taxonomy hint for `subject_areas`.

Also capture their **strategic plan document** as a `Funder.notes` artifact.
Strategic plans shift every 3-5 years and shift priorities significantly; a
diff signal here is high value.

---

## 7. Philanthropy News Digest RFPs (`pnd_rfp`)

### What and why

Candid's free RFP listing, national in scope. Use as a **discovery layer** —
PND surfaces national funders that occasionally do place-based DMV work,
which we'd otherwise miss. The canonical record is on the funder's own site;
PND is the breadcrumb.

### Access

`philanthropynewsdigest.org/rfps` plus the RSS feed for incremental updates.

### Fields to extract

| PND field | Unified |
|---|---|
| Title | `OpportunityInstance.title` |
| Funder name | (resolve to `Funder.canonical_name`) |
| Deadline | `application_close_at` |
| Amount info (text) | `award_min`/`award_max` after parse |
| Eligibility (text) | (drives extraction of `eligibility` struct) |
| Geographic scope (text) | `geographic_scope` |
| URL to source | (triggers a fetch of the funder's own page as a separate raw record) |
| Summary | (used for retrieval) |

### Normalization

- PND mixes national and regional. Pre-filter by `geographic_scope` containing
  "national," "DC," "MD," "VA," or "DMV" before triggering downstream fetch
  of the source page.
- The PND record is a hint; the source-page record is the truth. Link them in
  the source_records list of the resulting `OpportunityInstance`.

---

## 8. Aggregator platforms: Submittable, ProjectStream, Foundant (`submittable`, `projectstream`, `foundant`)

### What and why

Many foundations use these as their application backend. Each has a
public-facing discovery interface. Value: schema consistency across many
funders. A Submittable listing has the same fields no matter which foundation
posted it.

### Access

- Submittable Discover: `submittable.com/discover` with category/location
  filters.
- Foundant GLM: foundation-by-foundation, but URL pattern is consistent
  (`foundationname.foundantmarketplace.com` or similar).
- ProjectStream: similar.

### Fields (Submittable as representative)

| Submittable field | Unified |
|---|---|
| Title | `OpportunityInstance.title` |
| Organization (the funder using Submittable) | `Funder.canonical_name` |
| Submission deadline | `application_close_at` |
| Open date | `application_open_at` |
| Category | `subject_areas` |
| Description | (raw text) |
| Submission requirements | (raw text) |
| Form fields (if visible) | (informs `eligibility` extraction) |
| URL | (canonical) |

### Normalization

- Cross-reference each "organization" on Submittable against the funder
  registry (built from 990-PF). Submittable is a portal; the underlying
  funder is what matters.
- Submittable Discover includes art submissions, contests, literary mags —
  filter aggressively to nonprofit grants only.

### Gotchas

- Many Submittable listings are visible only when open. Off-cycle visibility
  requires either Wayback or noting the URL during the previous cycle.
- Foundant URLs are foundation-specific; maintaining the list overlaps with
  `pf_*`.

---

## 9. grants.gov (`grants_gov`)

### What and why

Federal grant opportunities. For our segment, ~5% relevance — most federal
direct grants don't fit small CBOs. Worth including for:

- ED grants targeting community-based providers (Promise Neighborhoods, Full-
  Service Community Schools).
- HHS ACF Youth Services (Runaway and Homeless Youth, Chafee).
- DOJ OJJDP youth programs.
- Occasional Corp for National and Community Service / AmeriCorps state pots.

### Access

Two paths:

1. **Daily XML extract** (preferred for bulk): grants.gov publishes a zip of
   all open opportunities daily.
2. **REST API** (preferred for queries): `api.grants.gov` — verify endpoint
   shape before coding.

### Fields to extract

| grants.gov field | Unified |
|---|---|
| `OpportunityNumber` | `OpportunityInstance.notes['fed_opp_number']` |
| `OpportunityTitle` | `title` |
| `Agency` | `Funder.canonical_name` (funder_type=govt_federal) |
| `CFDANumber` / Assistance Listing | `notes['cfda']` |
| `PostDate` | `first_seen_at` (override) |
| `CloseDate` | `application_close_at` |
| `AwardCeiling` | `award_max` |
| `AwardFloor` | `award_min` |
| `EstimatedTotalProgramFunding` | `total_pool` |
| `ExpectedNumberOfAwards` | `notes['num_awards']` |
| `EligibleApplicants` (codes) | `eligibility.org_type` |
| `FundingInstrumentType` | `notes['funding_instrument']` |
| `CategoryOfFundingActivity` | `subject_areas` |
| `Description` (often a PDF link) | (raw record + fetch the linked RFP) |
| `Synopsis` | (raw text for retrieval) |

### Filtering

Pre-filter to relevance before storing:

- `EligibleApplicants` includes code 25 (nonprofit with 501c3) or 12 (other
  nonprofit).
- `CFDANumber` in {84.*, 93.5*, 16.*} or category code in {E, ED, HL}.
- `AwardFloor` (when present) is below $250K, or absent (don't drop on
  amount alone).

Records that don't pass: store the raw, skip the OpportunityInstance creation.
We may want them later for the funder graph even if they're not user-facing.

### Gotchas

- Federal RFPs are dense PDFs (50-200 pages). Don't try to extract everything
  at ingest; capture the structured fields from the XML extract and treat the
  PDF as a raw record. Extraction of eligibility from the PDF body is a
  separate, model-versioned step.
- CFDA numbers got renamed to "Assistance Listing" numbers around 2020 — same
  thing, different name. Tolerate both.

---

## 10. Internet Archive Wayback Machine (`wayback_*`)

### What and why

The Internet Archive periodically captures snapshots of public web pages and
exposes them via the CDX server API. For grant pages that disappear after
their deadline — the dominant failure mode of community-foundation and
private-foundation sites — Wayback frequently has historical captures.

We use it for two things:

1. **Off-cycle backfill.** When a `cf_*` or `pf_*` adapter encounters a URL
   that returns 404 or has been redirected, query Wayback for prior captures
   and ingest the most recent successful one. This populates the
   funder's program calendar for prior cycles without our having scraped
   them live.
2. **Monthly sweep for known funders.** For each funder in the registry,
   query Wayback's CDX for new captures since last sweep and ingest any
   captures of pages we haven't seen. Catches pages that exist briefly
   between our scheduled fetches.

Without Wayback, the corpus is biased toward grant pages that happened to be
open during our active ingest windows. That bias propagates into the
training data for retrieval and ranking models. Backfilling closes the gap.

### Access

- **CDX server API:** `https://web.archive.org/cdx/search/cdx` returns a list
  of captures for a URL, with timestamps and status codes. Verify endpoint
  shape before coding — Internet Archive APIs have moved before.
- **Wayback content:**
  `https://web.archive.org/web/<timestamp>id_/<original_url>` returns the
  raw archived content without Wayback's chrome (the `id_` modifier strips
  their injected toolbar).
- Free, no auth, rate-limit politely. The CDX API tolerates higher rates
  than the content endpoint.

### Output

Wayback adapters produce raw records exactly like live adapters. The
`source_id` is the originating adapter prefixed with `wayback_` (e.g.
`wayback_cf_gwcf`) so downstream code can identify the provenance. The
`fetch_metadata` sidecar carries the Wayback timestamp and the original
URL separately from the Wayback-wrapped URL.

### Cadence

- On-demand: triggered automatically by any adapter that encounters a 404 or
  redirect on a URL it has previously ingested successfully.
- Monthly sweep: scheduled job iterates funders in the registry, queries
  CDX for new captures since last sweep, fetches captures we don't already
  have under their `content_sha`.

### Gotchas

- Wayback captures sometimes include the live page's broken state (404,
  500, JavaScript-blocked). Check HTTP status in CDX results before fetching
  content; skip captures where the original status was an error.
- Capture frequency is uneven — some sites have weekly snapshots, some have
  one capture per year. The off-cycle calendar reconstruction is best-effort,
  not exhaustive.
- Wayback content can be heavy (their toolbar adds size even with `id_`).
  Strip remaining Wayback-injected markup before storing if needed for
  downstream parser sanity.
- Robots.txt: Wayback historically honored a now-deprecated retroactive
  robots.txt rule. Captures may disappear if the live site changes its
  policy. Don't assume captures are permanently available; if you depend
  on one for an evaluation, ingest it into your own object store
  immediately.

---

## Cross-cutting

### Identity resolution at ingest

Each adapter emits a candidate `OpportunityInstance` with `funder_id` and
`program_id` set to `None` and a `funder_name_raw` / `program_name_raw` pair.
A separate entity-resolution stage runs after raw extraction.

**v1 approach: exact-match-after-normalize.** At the corpus scale this
component targets (~200 funders, ~500 programs), fuzzy matching is overkill
and introduces failure modes that are worse than the problem it solves.

Funder resolution:

1. Normalize `funder_name_raw`: lowercase, strip punctuation, strip
   suffixes (`foundation`, `fund`, `trust`, `inc`, `incorporated`, `the`),
   collapse whitespace.
2. Exact-match the normalized string against the `Funder` registry's
   `canonical_name` and `aliases` (also normalized).
3. If EIN is known, prefer EIN match over name match.
4. Hit → write `ResolutionEvent` with `confidence='exact'`, populate
   `funder_id`.
5. Miss → write `ResolutionEvent` with `confidence='none'`, leave
   `funder_id=None`, add to the manual-review queue.

Program resolution: same logic against the funder's existing programs, run
only after funder resolution succeeds.

Manual-review queue is a SQL query against unresolved records, exported
weekly. Resolve by adding the variant string to the existing funder's
`aliases` list (in which case the next pass auto-resolves), or by creating
a new `Funder` record. Both actions log events.

No fuzzy matching, no thresholds, no Levenshtein in v1. Revisit when the
unresolved queue exceeds 50 items per week sustained, or when the corpus
crosses ~1,000 funders.

Don't try to be clever at ingest. Resolution is its own pipeline stage.

### State transitions

Each fetch updates `last_seen_at`. The state machine runs on a schedule
(daily) and computes transitions:

- Seen this fetch + previously open + past close date → `closed`
- Not seen this fetch + previously open + < 14 days since last seen →
  `unreachable`
- Not seen + `unreachable` for >= 14 days → `provisionally_withdrawn`
- Not seen + `provisionally_withdrawn` for >= 60 days → `withdrawn`
- Re-seen at any time → reset to previous valid state

Don't delete. Status transitions are events; the event log is authoritative.

### Content-addressed storage

Every fetch writes to:

```
s3://uc-corpus/raw/<source_id>/<yyyy>/<mm>/<sha256[:2]>/<sha256>.bin
```

with a metadata sidecar:

```
s3://uc-corpus/raw/<source_id>/<yyyy>/<mm>/<sha256[:2]>/<sha256>.json
```

containing `fetch_url`, `fetched_at`, HTTP headers, MIME type, source adapter
version. The sidecar is the only thing that ever varies for the same
`content_sha`; the bytes are immutable.

For local dev / first month, use a filesystem layout under
`/var/lib/uc-corpus/` with the same structure. S3 migration is a config flip.

### Event log

SQLite table, append-only, indexed by `(source_id, timestamp)` and
`(opportunity_id, timestamp)`:

```python
class CorpusEvent:
    id: int                    # autoincrement
    timestamp: datetime
    event_type: str            # seen / parsed / extracted / resolved / merged / split / status_changed / withdrawn
    source_id: str
    content_sha: Optional[str]
    opportunity_id: Optional[UUID]
    funder_id: Optional[UUID]
    program_id: Optional[UUID]
    payload: dict              # event-specific data
    actor: str                 # 'system:adapter_v0.3.1' or 'user:chris'
```

This is the source of truth. Materialized views over the event log produce
the current `OpportunityInstance` / `Funder` / `Program` tables, which can be
rebuilt at any time.

### Snapshot tags

A snapshot tag is a row:

```python
class CorpusSnapshot:
    tag: str                   # 'corpus-2026-05-17'
    event_log_position: int    # max event id at snapshot time
    object_store_manifest_ref: str  # hash of the list of content_shas at snapshot time
    created_at: datetime
    notes: str
```

Training runs and evaluations reference a tag. Reproducibility is:
`(snapshot_tag, extractor_model_sha, extractor_code_git_sha, schema_version, filter_query, seeds)`.

**Snapshot frequency.** Tag a snapshot at every training run, every formal
evaluation run, and at the start of every milestone. Ad-hoc snapshots are
allowed and encouraged whenever a measurement would be worth reproducing
later (e.g., a comparison the implementer wants to be able to back to).
Snapshots are cheap — a row plus a manifest hash — so the rule is err
toward more. Source fetch cadence (see the source register table) is a
separate concept; that controls when scrapers run, not when snapshots get
tagged.

### Provenance per record

Every `OpportunityInstance` carries an `ExtractionTrace`:

```python
class ExtractionTrace:
    source_records: list[str]               # content_shas
    parser_version: str
    extractor_model_version: str
    extractor_code_git_sha: str
    schema_version: str
    field_confidences: dict[str, float]     # per-field
    field_provenance: dict[str, str]        # which source_record each field came from
```

`field_provenance` is what lets a user (or a debug tool) ask "where did
'$50K-$200K' come from?" and get a pointer back to the exact raw record.

### Ingestion health metrics

Component 1 needs its own health signal independent of the end-to-end
evaluation harness (Component 7). The downstream eval measures the system;
these metrics measure the pipeline that feeds it.

Tracked per source, recorded daily into a `IngestHealthSnapshot` table:

| Metric | Definition | Alert threshold |
|---|---|---|
| `fetch_success_rate` | Fraction of attempted fetches in the last 24h returning 2xx | < 0.9 sustained for 3 days |
| `parse_error_rate` | For Tier A only: fraction of records that failed structured parsing | > 0.05 for any source |
| `freshness_lag` | Median hours between source's `last_modified` and our `fetched_at` | > 2x configured cadence |
| `coverage_ratio` | Records ingested in trailing 90 days / baseline expected for source | < 0.5 |
| `unresolved_queue_depth` | Manual-review queue length | > 50 sustained for 1 week |
| `wayback_backfill_hit_rate` | Wayback queries returning usable captures | informational, no alert |

Baseline expected counts per source come from two sources:

- For `irs_990pf`: derived from the funder's historical filing pattern.
- For `cf_*`, `pf_*`, `gov_*`: a configurable annual expectation set per
  source in the adapter config (e.g., "GWCF posts ~12 opportunities/year").
  Updated by hand when an implementer notices it's off.

Implementation: one Django management command, scheduled daily, writes a
row per `(source_id, metric)` pair. A second command reads the latest
rows and emits Slack/email alerts when thresholds trip. No dashboarding in
v1; query the table with SQL when investigating.

---

## Build order

Don't try to do all ten sources at once. Order:

1. **`irs_990pf` + `propublica_np`** — build the funder registry first. Every
   later source needs to resolve funders, and the registry is the
   highest-signal asset we own. (1-2 weeks)
2. **`pnd_rfp`** — easy win, structured RSS, exercises the full pipeline end-
   to-end on real grant data without per-portal complexity. (2-3 days)
3. **`grants_gov`** — XML extract is straightforward and exercises the
   federal-grants slice. (3-5 days)
4. **`cf_gwcf` + `cf_cfnova` + `cf_arlcf` + `cf_cfmoco` + `cf_pgcf`** — the
   five most-important DMV community foundations. Build the per-portal
   adapter pattern. (1-2 weeks)
5. **`wayback_*` adapter shell + monthly sweep for the funders ingested so
   far** — established here so subsequent adapters inherit the on-404
   fallback automatically. Visibility gap from prior cycles starts closing
   immediately. (3-5 days)
6. **`pf_*` (top 10-15 foundations to start)** — config-driven raw fetch
   pattern. Don't try for 50 in week one. (1-2 weeks)
7. **`gov_*` (DC OSSE, MSDE, FFX CCFP first)** — exercise the PDF-handling
   path. (1-2 weeks)
8. **`uwnca`, `submittable`, `foundant`, `projectstream`** — aggregator
   coverage. (1 week)
9. **Expand `pf_*` to 50, expand `gov_*` to county-level coverage** — long
   tail. Ongoing.

Total: ~8-12 weeks of part-time work for a complete Component 1, with the
critical path (funder registry + a working end-to-end pipeline on PND) done
in week 1-2.

## Open questions for the implementer

- **Storage:** start filesystem-only or S3 from day one? Recommend filesystem
  with a clean abstraction layer; S3-migrate in month 2.
- **Manual review queue:** UI? CLI? Initially, a SQL query + spreadsheet
  export is fine. Build a Django admin view once volumes justify it.
- **Robots.txt and rate limits:** strict compliance from day one. One
  blocklist incident with a foundation site will damage the trust the product
  depends on.

---

## Appendix: ADR-001 — Ingestion infrastructure additions

> This ADR belongs at `/docs/decisions/2026-05-18-ingestion-infrastructure.md`
> in the repo. It is embedded here for now so the spec is self-contained;
> extract on commit.

**Date:** 2026-05-18
**Status:** Accepted
**Authors:** Chris

### Context

The lean-stack invariant in `CLAUDE.md` requires an ADR for any new
infrastructure beyond Django + Postgres + Railway. Component 1 introduces
several pieces that collectively expand the stack and warrant recording.

### Decision

The following infrastructure is added for grant corpus ingestion:

1. **Content-addressed object store for raw records.** Filesystem-backed in
   local dev (`/var/lib/uc-corpus/`), S3-backed in production
   (`s3://uc-corpus/`). Same directory layout in both. Switch is a config
   flag.

2. **Playwright** for JavaScript-rendered portals. Used only by adapters
   whose source config declares `render: js`. Plain `httpx` is the default.

3. **Scheduled scraper runners.** Implemented as Django management commands
   invoked by cron on Railway in v1. Cadence per source declared in the
   source register. Migrate to a job queue (Django-Q2 or RQ — see existing
   open question in `CLAUDE.md`) once adapter count justifies it.

4. **SQLite-backed corpus event log.** Append-only `CorpusEvent` table in
   its own database file (`uc_corpus_events.sqlite`), separate from the
   main Django app DB. Materialized views (rebuildable from the event log)
   produce current state for `Funder`, `Program`, `OpportunityInstance`.

5. **Internet Archive Wayback Machine adapter** for off-cycle backfill and
   monthly sweep of registered funders. Uses CDX API; no auth.

6. **Daily ingestion-health metrics job.** Django management command that
   computes the metrics defined in the *Ingestion health metrics* section
   and writes to an `IngestHealthSnapshot` table.

### Consequences

- Ingestion runs as a separate service surface from the user-facing Django
  app. On Railway, this is a scheduled worker (cron-driven management
  command), not the web dyno.
- The corpus event-log database is a second source of truth alongside the
  main app's ORM. Reconciliation is bounded: the event log is the truth,
  materialized tables can be rebuilt from it, no two-way sync.
- Playwright adds ~500MB to the container image and noticeable CPU cost.
  Acceptable for ingestion (offline, scheduled); would be unacceptable in
  the user-facing web path. Build a separate image for the ingestion worker
  if image size becomes an issue.
- Filesystem-to-S3 migration is a config flip but requires backfilling the
  existing local corpus to S3 on first production deploy. Treat as a
  one-time migration script, not an incremental sync.
- The cron-driven approach has no retry semantics on failure beyond the
  next scheduled run. Acceptable for v1; revisit when adapter failures
  become a regular operational concern.

### Alternatives considered

- **Scrapy framework.** Rejected: heavier than needed for ten sources, and
  its abstractions assume parse-at-fetch which contradicts the Tier B/C
  raw-only commitment.
- **Postgres for the event log.** Rejected: SQLite append-only is
  sufficient, cheaper, and isolates the event log's failure modes from the
  main app DB.
- **Per-source containers / microservices.** Rejected: overkill for
  solo-dev maintenance. One worker process per cadence (daily / weekly /
  quarterly) iterating over its sources is enough.
- **Replacing event log with Postgres triggers / outbox.** Rejected:
  ingestion runs in a process that may not have a live Postgres connection
  during long scrape sessions. The SQLite event log is local and
  durable to that.

---

*End of spec.*
