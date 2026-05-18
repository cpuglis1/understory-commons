"""IRS990PFAdapter — parses 990-PF XML filings from URLs in the funder registry.

source_id: irs_990pf
version:   0.1.0
Rate limit: 1 req/sec (same ProPublica XML URLs)
Auth: none

parse() emits:
  historical_grant_recorded  — one event per Part XV-1 grant row
  funder_enriched            — one event per filing with Part XV-2 application text
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from typing import ClassVar

from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.raw_record import RawRecord
from grants_ingest.storage.base import RawObjectStore

from .base import BaseAdapter
from .event_log import EventLogWriter
from .types import FetchTask

logger = logging.getLogger(__name__)

# IRS 990-PF XML uses these namespace prefixes in modern e-file submissions.
_NS = {
    "irs": "http://www.irs.gov/efile",
}


def _find_text(el: ET.Element, path: str, ns: dict | None = None) -> str:
    found = el.find(path, ns or _NS)
    return (found.text or "").strip() if found is not None else ""


class IRS990PFAdapter(BaseAdapter):
    source_id: ClassVar[str] = "irs_990pf"
    version: ClassVar[str] = "0.1.0"
    rate_limit_per_sec: ClassVar[float] = 1.0
    robots_compliance: ClassVar[str] = "strict"

    def __init__(
        self,
        store: RawObjectStore,
        event_log: EventLogWriter,
        filing_urls: list[dict] | None = None,
    ) -> None:
        """
        filing_urls: list of {"ein": "...", "url": "...", "year": int}
        Built from Funder.notes['filings_index'] by the management command.
        """
        super().__init__(store=store, event_log=event_log)
        self._filing_urls: list[dict] = filing_urls or []

    def iter_fetch_tasks(self, **kwargs) -> Iterable[FetchTask]:
        for entry in self._filing_urls:
            yield FetchTask(
                url=entry["url"],
                expected_mime="application/xml",
                extra_metadata={"ein": entry.get("ein", ""), "tax_year": entry.get("year")},
            )

    def parse(self, raw: RawRecord) -> list[tuple[CorpusEventType, dict]]:
        body = self.store.get(raw.content_sha)
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            logger.error("irs_990pf: XML parse error for %s: %s", raw.content_sha, exc)
            return [(CorpusEventType.PARSE_FAILED, {"error": str(exc), "sha": raw.content_sha})]

        events: list[tuple[CorpusEventType, dict]] = []

        filer_ein = _find_filer_ein(root)
        tax_year = _find_tax_year(root)

        # Part XV-1: grant rows
        grant_rows = _extract_part_xv1(root, filer_ein, tax_year)
        for row in grant_rows:
            events.append((CorpusEventType.HISTORICAL_GRANT_RECORDED, row))

        # Part XV-2: application info text -> funder_enriched
        enrichment = _extract_part_xv2(root, filer_ein)
        if enrichment:
            events.append((CorpusEventType.FUNDER_ENRICHED, enrichment))

        return events


# ---------------------------------------------------------------------------
# XML extraction helpers
# ---------------------------------------------------------------------------


def _find_filer_ein(root: ET.Element) -> str:
    # Try namespaced path first, then unqualified
    for path in [
        ".//irs:Filer/irs:EIN",
        ".//Filer/EIN",
        ".//ReturnHeader/Filer/EIN",
    ]:
        ns = _NS if path.startswith(".//irs:") else {}
        val = _find_text(root, path, ns)
        if val:
            return val.replace("-", "")
    return ""


def _find_tax_year(root: ET.Element) -> int:
    for path in [
        ".//irs:TaxYear",
        ".//TaxYear",
        ".//ReturnHeader/TaxYear",
        ".//TaxPeriodEndDt",
    ]:
        ns = _NS if path.startswith(".//irs:") else {}
        val = _find_text(root, path, ns)
        if val:
            try:
                return int(val[:4])
            except ValueError:
                pass
    return 0


def _extract_part_xv1(root: ET.Element, filer_ein: str, tax_year: int) -> list[dict]:
    rows = []
    # Search both namespaced and plain for grant group elements
    grant_paths = [
        ".//irs:GrantOrContributionPdDurYrGrp",
        ".//GrantOrContributionPdDurYrGrp",
    ]
    for path in grant_paths:
        ns = _NS if "irs:" in path else {}
        for grp in root.findall(path, ns):
            recipient_name = _find_recipient_name(grp)
            amount_str = (
                _find_text(grp, "irs:Amt", _NS)
                or _find_text(grp, "Amt")
                or _find_text(grp, "irs:CashGrantAmt", _NS)
                or _find_text(grp, "CashGrantAmt")
            )
            if not recipient_name or not amount_str:
                continue
            try:
                amount = float(amount_str.replace(",", ""))
            except ValueError:
                continue

            row = {
                "funder_ein": filer_ein,
                "tax_year": tax_year,
                "recipient_name_raw": recipient_name,
                "recipient_address_raw": _find_recipient_address(grp),
                "recipient_ein": _find_recipient_ein(grp),
                "amount": str(amount),
                "purpose": (
                    _find_text(grp, "irs:GrantOrContributionPurposeTxt", _NS)
                    or _find_text(grp, "GrantOrContributionPurposeTxt")
                ),
                "relationship_flag": (
                    _find_text(grp, "irs:RecipientRelationshipTxt", _NS)
                    or _find_text(grp, "RecipientRelationshipTxt")
                ),
            }
            rows.append(row)
        if rows:
            break
    return rows


def _find_recipient_name(grp: ET.Element) -> str:
    for path in [
        "irs:RecipientBusinessName/irs:BusinessNameLine1Txt",
        "RecipientBusinessName/BusinessNameLine1Txt",
        "irs:RecipientPersonNm",
        "RecipientPersonNm",
    ]:
        ns = _NS if "irs:" in path else {}
        val = _find_text(grp, path, ns)
        if val:
            return val
    return ""


def _find_recipient_ein(grp: ET.Element) -> str:
    for path in ["irs:RecipientEIN", "RecipientEIN"]:
        ns = _NS if "irs:" in path else {}
        val = _find_text(grp, path, ns)
        if val:
            return val.replace("-", "")
    return ""


def _find_recipient_address(grp: ET.Element) -> str:
    parts = []
    for field in ["AddressLine1Txt", "CityNm", "StateAbbreviationCd", "ZIPCd"]:
        for prefix in ["irs:RecipientUSAddress/irs:", "RecipientUSAddress/"]:
            val = _find_text(grp, f"{prefix}{field}", _NS if "irs:" in prefix else {})
            if val:
                parts.append(val)
                break
    return ", ".join(parts)


def _extract_part_xv2(root: ET.Element, filer_ein: str) -> dict | None:
    notes: dict = {}
    fields = {
        "application_info_text": [
            "irs:ApplicationSubmissionInfoTxt",
            "ApplicationSubmissionInfoTxt",
        ],
        "restrictions_text": [
            "irs:DistributionToOrganizationsTxt",
            "DistributionToOrganizationsTxt",
        ],
        "award_limitations_text": [
            "irs:LimitationOnAwardsTxt",
            "LimitationOnAwardsTxt",
        ],
    }
    for key, paths in fields.items():
        for path in paths:
            ns = _NS if "irs:" in path else {}
            val = _find_text(root, f".//{path}", ns)
            if val:
                notes[key] = val
                break

    if not notes or not filer_ein:
        return None
    return {"ein": filer_ein, "notes": notes}
