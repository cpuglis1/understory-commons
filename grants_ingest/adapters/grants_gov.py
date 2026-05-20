"""GrantsGovAdapter — daily XML extract from grants.gov.

Fetch path: one zip download per run containing every currently open
opportunity. Unzip in-memory, iterparse the XML (bounded memory regardless
of extract size), apply three pre-filter rules, emit OPPORTUNITY_SEEN for
passes and OPPORTUNITY_FILTERED for failures.

PDF fetch (Description URL that ends in .pdf) is added in commit #6.
"""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar

from grants_ingest.corpus_event import CorpusEventType

from .base import BaseAdapter
from .types import FetchTask

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

    def iter_fetch_tasks(self, **kwargs):
        yield FetchTask(url=self.extract_url, expected_mime="application/zip")

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

        # PDF description URL — stored in notes, fetched separately in commit #6
        if description and _looks_like_pdf_url(description):
            payload["notes"]["description_pdf_url"] = description

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
