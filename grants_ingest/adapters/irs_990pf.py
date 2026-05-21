"""IRS990PFAdapter — parses 990-PF XML filings from IRS monthly batch zips.

source_id: irs_990pf
version:   0.2.0
Rate limit: 1 req/sec (applies to zip downloads, not per-entry parsing)
Auth: none

Batch-zip URL pattern (verified live 2026-05-21):
  https://apps.irs.gov/pub/epostcard/990/xml/{YYYY}/{YYYY}_TEOS_XML_{MM}{LETTER}.zip
  LETTER = A, B, C per month. Current month may return 302 (not yet posted); skip.

parse() emits (per matching 990-PF XML entry):
  historical_grant_recorded  — one event per Part XV-1 grant row
  funder_enriched            — one event per filing with Part XV-2 application text
"""

from __future__ import annotations

import io
import logging
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable
from datetime import date
from typing import ClassVar
from urllib.parse import urlparse

import httpx
from django.utils import timezone

from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.raw_record import RawRecord
from grants_ingest.storage.base import RawObjectStore

from .base import _DEFAULT_HEADERS, BaseAdapter
from .event_log import EventLogWriter
from .http import compute_sha
from .types import AdapterRunResult, FetchTask

logger = logging.getLogger(__name__)

_IRS_ZIP_URL = (
    "https://apps.irs.gov/pub/epostcard/990/xml" "/{year}/{year}_TEOS_XML_{mm}{letter}.zip"
)

_NS = {
    "irs": "http://www.irs.gov/efile",
}


def _find_text(el: ET.Element, path: str, ns: dict | None = None) -> str:
    found = el.find(path, ns or _NS)
    return (found.text or "").strip() if found is not None else ""


class IRS990PFAdapter(BaseAdapter):
    source_id: ClassVar[str] = "irs_990pf"
    version: ClassVar[str] = "0.2.0"
    rate_limit_per_sec: ClassVar[float] = 1.0
    robots_compliance: ClassVar[str] = "strict"

    def __init__(
        self,
        store: RawObjectStore,
        event_log: EventLogWriter,
        seed_eins: list[str] | None = None,
        months_back: int = 3,
    ) -> None:
        super().__init__(store=store, event_log=event_log)
        self._seed_eins: set[str] = {e.replace("-", "") for e in (seed_eins or [])}
        self.months_back = months_back

    def iter_fetch_tasks(self, **kwargs) -> Iterable[FetchTask]:
        today = date.today()
        for i in range(self.months_back):
            month = today.month - i
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            mm = f"{month:02d}"
            for letter in "ABC":
                url = _IRS_ZIP_URL.format(year=year, mm=mm, letter=letter)
                yield FetchTask(url=url, expected_mime="application/zip")

    def run(self, **kwargs) -> AdapterRunResult:
        result = AdapterRunResult(source_id=self.source_id)
        last_req: dict[str, float] = {}
        min_gap = 1.0 / self.rate_limit_per_sec

        with httpx.Client(follow_redirects=False, headers=_DEFAULT_HEADERS, timeout=360) as client:
            for task in self.iter_fetch_tasks(**kwargs):
                host = urlparse(task.url).netloc
                elapsed = time.monotonic() - last_req.get(host, 0.0)
                if elapsed < min_gap:
                    time.sleep(min_gap - elapsed)
                last_req[host] = time.monotonic()

                try:
                    resp = client.get(task.url)
                except Exception as exc:
                    logger.error("irs_990pf: fetch error %s: %s", task.url, exc)
                    result.errors.append(str(exc))
                    continue

                if resp.status_code in (302, 404):
                    logger.debug("irs_990pf: skip %s (HTTP %d)", task.url, resp.status_code)
                    continue

                if resp.status_code != 200:
                    logger.warning("irs_990pf: HTTP %d for %s", resp.status_code, task.url)
                    result.errors.append(f"HTTP {resp.status_code}: {task.url}")
                    continue

                result.fetched += 1
                logger.info("irs_990pf: processing %s (%d bytes)", task.url, len(resp.content))
                try:
                    self._process_zip(resp.content, task.url, result)
                except zipfile.BadZipFile as exc:
                    logger.error("irs_990pf: bad zip %s: %s", task.url, exc)
                    result.errors.append(str(exc))

        return result

    def _process_zip(self, zip_bytes: bytes, zip_url: str, result: AdapterRunResult) -> None:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for entry_name in zf.namelist():
                if not entry_name.lower().endswith(".xml"):
                    continue
                xml_bytes = zf.read(entry_name)
                self._process_entry(xml_bytes, entry_name, zip_url, result)

    def _process_entry(
        self,
        xml_bytes: bytes,
        entry_name: str,
        zip_url: str,
        result: AdapterRunResult,
    ) -> None:
        is_match, ein = _should_process(xml_bytes, self._seed_eins)
        if not is_match:
            return

        sha = compute_sha(xml_bytes)
        fetched_at = timezone.now()
        sidecar = {
            "source_id": self.source_id,
            "fetch_url": zip_url,
            "zip_entry": entry_name,
            "fetched_at": fetched_at.isoformat(),
            "mime_type": "application/xml",
            "http_status": 200,
            "ein": ein,
        }
        content_ref = self.store.put(sha, xml_bytes, sidecar)
        is_new = not RawRecord.objects.filter(content_sha=sha).exists()

        if is_new:
            raw = RawRecord.objects.create(
                content_sha=sha,
                fetch_url=zip_url,
                fetched_at=fetched_at,
                source_id=self.source_id,
                mime_type="application/xml",
                content_ref=content_ref,
                http_status=200,
                fetch_metadata={"zip_entry": entry_name, "ein": ein},
            )
            result.stored_new += 1
        else:
            raw = RawRecord.objects.get(content_sha=sha)

        self.event_log.append(
            CorpusEventType.SEEN,
            content_sha=sha,
            payload={"url": zip_url, "zip_entry": entry_name, "is_new": is_new},
        )

        try:
            events = self.parse(raw)
            for event_type, payload in events:
                self.event_log.append(event_type, payload=payload, content_sha=sha)
        except Exception as exc:
            logger.error("irs_990pf: parse error %s/%s: %s", zip_url, entry_name, exc)
            result.parse_errors += 1
            result.errors.append(str(exc))

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

        for row in _extract_part_xv1(root, filer_ein, tax_year):
            events.append((CorpusEventType.HISTORICAL_GRANT_RECORDED, row))

        enrichment = _extract_part_xv2(root, filer_ein)
        if enrichment:
            events.append((CorpusEventType.FUNDER_ENRICHED, enrichment))

        return events


# ---------------------------------------------------------------------------
# Filter helper
# ---------------------------------------------------------------------------


def _should_process(xml_bytes: bytes, seed_eins: set[str]) -> tuple[bool, str]:
    """Return (should_keep, ein). Checks ReturnTypeCd and Filer/EIN."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return False, ""

    return_type = ""
    for path in [".//irs:ReturnTypeCd", ".//ReturnTypeCd"]:
        ns = _NS if "irs:" in path else {}
        val = _find_text(root, path, ns)
        if val:
            return_type = val
            break

    if return_type.upper() != "990PF":
        return False, ""

    ein = _find_filer_ein(root)
    return ein in seed_eins, ein


# ---------------------------------------------------------------------------
# XML extraction helpers (unchanged from v0.1.0)
# ---------------------------------------------------------------------------


def _find_filer_ein(root: ET.Element) -> str:
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

            rows.append(
                {
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
            )
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
