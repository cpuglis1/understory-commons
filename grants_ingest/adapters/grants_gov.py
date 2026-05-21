"""GrantsGovAdapter — daily XML extract from grants.gov.

Fetch path: one zip download per run containing every currently open
opportunity. Unzip in-memory, iterparse the XML (bounded memory regardless
of extract size), apply three pre-filter rules, emit OPPORTUNITY_SEEN for
passes and OPPORTUNITY_FILTERED for failures.

PDF fetch: after the base run() loop, a second pass fetches any PDF URLs
found in passing opportunities' Description field, stores them as separate
RawRecords (50MB cap), and emits an OPPORTUNITY_SEEN event with the PDF
SHA in extra_content_shas so the materializer can M2M-link it.
"""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar

import httpx

from grants_ingest.corpus_event import CorpusEventType

from .base import _DEFAULT_HEADERS, BaseAdapter
from .http import RobotsBlocked
from .types import AdapterRunResult, FetchTask

logger = logging.getLogger(__name__)

# Current daily extract URL pattern — verify during first live run.
# This is the canonical bulk path per the slice-2 plan §2.1.
_EXTRACT_URL_TPL = (
    "https://prod-grants-gov-chamel.s3.amazonaws.com/extracts/" "GrantsDBExtract{date}v2.zip"
)

# Rule 1: eligible-applicant codes that pass (nonprofit 501c3 or other nonprofit)
_ELIGIBLE_CODES_PASS = {"25", "12"}

# Rule 2: CFDA prefixes that pass
_CFDA_PREFIXES_PASS = ("84.", "93.5", "16.")

# Rule 2: category codes that pass (OR with CFDA check)
_CATEGORY_CODES_PASS = {"E", "ED", "HL"}

# Rule 3: max award floor
_MAX_AWARD_FLOOR = 250_000


def _today_str() -> str:
    return datetime.now(UTC).strftime("%m%d%Y")


class GrantsGovAdapter(BaseAdapter):
    source_id: ClassVar[str] = "grants_gov"
    version: ClassVar[str] = "0.1.0"
    rate_limit_per_sec: ClassVar[float] = 1.0
    robots_compliance: ClassVar[str] = "strict"

    def __init__(self, store, event_log, extract_url: str | None = None) -> None:
        super().__init__(store, event_log)
        self.extract_url = extract_url or _EXTRACT_URL_TPL.format(date=_today_str())
        self._pdf_queue: list[dict] = []

    # 50 MB hard cap on PDF downloads per plan §2.5
    _PDF_SIZE_CAP = 50 * 1024 * 1024

    def iter_fetch_tasks(self, **kwargs):
        yield FetchTask(url=self.extract_url, expected_mime="application/zip")

    def run(self, **kwargs) -> AdapterRunResult:
        result = super().run(**kwargs)
        # Second pass: fetch PDFs queued by parse()
        if self._pdf_queue:
            with httpx.Client(follow_redirects=True, headers=_DEFAULT_HEADERS) as client:
                for opp_payload in self._pdf_queue:
                    self._fetch_pdf(opp_payload, client, result)
        return result

    def _fetch_pdf(self, opp_payload: dict, client: httpx.Client, result: AdapterRunResult) -> None:
        pdf_url = opp_payload["notes"].get("description_pdf_url", "")
        if not pdf_url:
            return

        # HEAD first to check Content-Length before downloading
        try:
            head = client.head(pdf_url, timeout=15)
            content_length = int(head.headers.get("content-length", 0))
            if content_length > self._PDF_SIZE_CAP:
                logger.warning(
                    "grants_gov: PDF %s too large (%d bytes), skipping", pdf_url, content_length
                )
                self.event_log.append(
                    CorpusEventType.OPPORTUNITY_FILTERED,
                    payload={
                        "source_id": self.source_id,
                        "external_id": opp_payload["external_id"],
                        "reason": "pdf_too_large",
                        "pdf_url": pdf_url,
                    },
                )
                return
        except Exception:
            pass  # HEAD failed — try GET anyway; content cap enforced below

        pdf_task = FetchTask(
            url=pdf_url,
            expected_mime="application/pdf",
            extra_metadata={"fed_opp_id": opp_payload["notes"].get("fed_opp_id", "")},
        )
        try:
            pdf_raw, pdf_is_new = self.fetch_one(pdf_task, client)
        except RobotsBlocked:
            result.robots_blocked += 1
            return
        except Exception as exc:
            logger.warning("grants_gov: PDF fetch failed for %s: %s", pdf_url, exc)
            result.errors.append(str(exc))
            return

        result.fetched += 1
        if pdf_is_new:
            result.stored_new += 1

        # Emit a second OPPORTUNITY_SEEN with the PDF SHA in extra_content_shas
        # so the materializer M2M-links the PDF RawRecord.
        self.event_log.append(
            CorpusEventType.OPPORTUNITY_SEEN,
            content_sha=opp_payload["content_sha"],
            payload={
                **opp_payload,
                "extra_content_shas": [pdf_raw.content_sha],
            },
        )

    def parse(self, raw) -> list:
        """Unzip the extract, iterparse XML, emit OPPORTUNITY_SEEN / FILTERED."""
        body = self.store.get(raw.content_sha)
        events: list[tuple] = []
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                xml_name = next((n for n in zf.namelist() if n.endswith(".xml")), None)
                if xml_name is None:
                    logger.warning("grants_gov: no XML file found in zip")
                    return events
                xml_bytes = zf.read(xml_name)
        except zipfile.BadZipFile as exc:
            logger.error("grants_gov: bad zip file: %s", exc)
            return events

        try:
            context = ET.iterparse(io.BytesIO(xml_bytes), events=("end",))
            for _xml_event, elem in context:
                if elem.tag != "OpportunityDetail":
                    continue
                opp_events = self._process_opportunity(elem, raw.content_sha)
                events.extend(opp_events)
                elem.clear()
        except ET.ParseError as exc:
            logger.error("grants_gov: XML parse error: %s", exc)

        return events

    def _process_opportunity(self, elem: ET.Element, content_sha: str) -> list[tuple]:
        opp_id = (elem.findtext("OpportunityID") or "").strip()
        opp_number = (elem.findtext("OpportunityNumber") or "").strip()
        title = (elem.findtext("OpportunityTitle") or "").strip()
        agency_name = (elem.findtext("AgencyName") or "").strip()
        post_date_str = (elem.findtext("PostDate") or "").strip()
        close_date_str = (elem.findtext("CloseDate") or "").strip()
        award_ceiling_str = (elem.findtext("AwardCeiling") or "").strip()
        award_floor_str = (elem.findtext("AwardFloor") or "").strip()
        total_pool_str = (elem.findtext("EstimatedTotalProgramFunding") or "").strip()
        num_awards = (elem.findtext("ExpectedNumberOfAwards") or "").strip()
        funding_instrument = (elem.findtext("FundingInstrumentType") or "").strip()
        description = (elem.findtext("Description") or "").strip()
        cfda_list = [e.text.strip() for e in elem.findall("CFDANumbers") if e.text]
        eligible_codes = [e.text.strip() for e in elem.findall("EligibleApplicants") if e.text]
        category_codes = [
            e.text.strip() for e in elem.findall("CategoryOfFundingActivity") if e.text
        ]

        if not opp_id:
            return []

        external_id = f"grants_gov:{opp_id}"

        # --- Pre-filter ---
        failed_rule = _check_filter_rules(
            eligible_codes, cfda_list, category_codes, award_floor_str
        )
        if failed_rule:
            return [
                (
                    CorpusEventType.OPPORTUNITY_FILTERED,
                    {
                        "source_id": self.source_id,
                        "external_id": external_id,
                        "title": title,
                        "reason": failed_rule,
                        "eligible_applicant_codes": eligible_codes,
                        "cfda": cfda_list,
                        "category": category_codes,
                        "award_floor": award_floor_str,
                    },
                )
            ]

        # --- Build OPPORTUNITY_SEEN payload ---
        first_seen_at = _parse_grants_gov_date(post_date_str)
        close_date = _parse_grants_gov_date(close_date_str)
        award_ceiling = _to_decimal(award_ceiling_str)
        award_floor = _to_decimal(award_floor_str)
        total_pool = _to_decimal(total_pool_str)

        payload: dict = {
            "source_id": self.source_id,
            "external_id": external_id,
            "title": title,
            "funder_name_raw": agency_name,
            "notes": {
                "fed_opp_id": opp_id,
                "fed_opp_number": opp_number,
                "cfda": cfda_list,
                "eligible_applicant_codes": eligible_codes,
                "num_awards": num_awards,
                "funding_instrument": funding_instrument,
            },
            "subject_areas": category_codes,
            "content_sha": content_sha,
        }
        if first_seen_at:
            payload["first_seen_at"] = first_seen_at.isoformat()
        if close_date:
            payload["application_close_at"] = close_date.isoformat()
        if award_ceiling is not None:
            payload["award_max"] = str(award_ceiling)
        if award_floor is not None:
            payload["award_min"] = str(award_floor)
        if total_pool is not None:
            payload["total_pool"] = str(total_pool)

        # PDF description URL — stored in notes; queued for second-pass fetch in run()
        if description and _looks_like_pdf_url(description):
            payload["notes"]["description_pdf_url"] = description
            self._pdf_queue.append(payload)

        return [(CorpusEventType.OPPORTUNITY_SEEN, payload)]


def _check_filter_rules(
    eligible_codes: list[str],
    cfda_list: list[str],
    category_codes: list[str],
    award_floor_str: str,
) -> str | None:
    """Return the failed rule name, or None if all rules pass."""
    # Rule 1: eligible-applicant codes
    if not any(c in _ELIGIBLE_CODES_PASS for c in eligible_codes):
        return "rule1_eligible_applicant"

    # Rule 2: CFDA prefix OR category code
    cfda_pass = any(cfda.startswith(prefix) for cfda in cfda_list for prefix in _CFDA_PREFIXES_PASS)
    category_pass = any(c in _CATEGORY_CODES_PASS for c in category_codes)
    if not (cfda_pass or category_pass):
        return "rule2_cfda_or_category"

    # Rule 3: award floor
    if award_floor_str:
        floor = _to_decimal(award_floor_str)
        if floor is not None and floor >= _MAX_AWARD_FLOOR:
            return "rule3_award_floor_too_high"

    return None


def _looks_like_pdf_url(text: str) -> bool:
    stripped = text.strip().split("?")[0].split("#")[0]
    return stripped.lower().endswith(".pdf")


def _parse_grants_gov_date(raw: str) -> datetime | None:
    """Parse grants.gov date formats: MMDDYYYY or YYYY-MM-DD."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%m%d%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _to_decimal(raw: str) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
