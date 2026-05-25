"""ProPublicaNPAdapter — fetches org JSON from ProPublica Nonprofit Explorer API.

source_id: propublica_np
version:   0.1.0
Rate limit: 1 req/sec
Auth: none
Input: seed list of EINs (dmv_foundations.yml)

parse() emits:
  funder_upserted — EIN, name, NTEE, address, subsection code, revenue index
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import ClassVar
from urllib.parse import parse_qs, unquote, urlparse

from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.raw_record import RawRecord
from grants_ingest.storage.base import RawObjectStore

from .base import BaseAdapter
from .event_log import EventLogWriter
from .types import FetchTask

logger = logging.getLogger(__name__)

PROPUBLICA_BASE = "https://projects.propublica.org/nonprofits/api/v2"


class ProPublicaNPAdapter(BaseAdapter):
    source_id: ClassVar[str] = "propublica_np"
    version: ClassVar[str] = "0.1.0"
    rate_limit_per_sec: ClassVar[float] = 1.0
    robots_compliance: ClassVar[str] = "strict"

    def __init__(
        self,
        store: RawObjectStore,
        event_log: EventLogWriter,
        seed_eins: list[str] | None = None,
    ) -> None:
        super().__init__(store=store, event_log=event_log)
        self._seed_eins: list[str] = seed_eins or []

    def iter_fetch_tasks(self, **kwargs) -> Iterable[FetchTask]:
        for ein in self._seed_eins:
            ein_clean = ein.replace("-", "")
            url = f"{PROPUBLICA_BASE}/organizations/{ein_clean}.json"
            yield FetchTask(
                url=url,
                expected_mime="application/json",
                extra_metadata={"ein": ein_clean},
            )

    def parse(self, raw: RawRecord) -> list[tuple[CorpusEventType, dict]]:
        body = self.store.get(raw.content_sha)
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            logger.error("propublica_np: JSON decode error for %s: %s", raw.content_sha, exc)
            return [(CorpusEventType.PARSE_FAILED, {"error": str(exc), "sha": raw.content_sha})]

        org = data.get("organization")
        if not org:
            logger.warning(
                "propublica_np: no organization data for %s (error=%r)",
                raw.content_sha,
                data.get("error"),
            )
            return []

        ein = str(org.get("ein", "")).replace("-", "") or None
        name = org.get("name", "")
        ntee = org.get("ntee_code") or ""
        subsection = str(org.get("subsection_code") or org.get("subseccd") or "")
        foundation_code = org.get("foundation_code")

        notes: dict = {}
        if ntee:
            notes["ntee"] = ntee
        if subsection:
            notes["irs_subsection"] = subsection

        address_parts = [
            org.get("address", ""),
            org.get("city", ""),
            org.get("state", ""),
            org.get("zipcode", ""),
        ]
        address = ", ".join(p for p in address_parts if p)
        if address:
            notes["address"] = address

        # Revenue by year from filings list
        annual_revenue: dict[str, str] = {}
        for filing in data.get("filings_with_data", []):
            year = str(filing.get("tax_prd_yr", ""))
            revenue = filing.get("totrevenue")
            if year and revenue is not None:
                annual_revenue[year] = str(revenue)
        if annual_revenue:
            notes["annual_revenue"] = annual_revenue

        # Build filings_index: 990-PF e-file XML URLs for the irs_990pf adapter.
        # ProPublica encodes e-filed documents as pdf_url with the IRS object_id
        # embedded as the last '_'-delimited filename component. We reconstruct
        # the canonical IRS S3 XML URL from that object_id.
        filings: list[dict] = []
        seen_urls: set[str] = set()
        for source_key in ("filings_with_data", "filings_without_data"):
            for f in data.get(source_key, []):
                if f.get("formtype") != 2:
                    continue
                object_id = _extract_object_id(f.get("pdf_url") or "")
                if not object_id:
                    continue
                xml_url = f"https://s3.amazonaws.com/irs-form-990/{object_id}_public.xml"
                if xml_url in seen_urls:
                    continue
                seen_urls.add(xml_url)
                filings.append({"year": f.get("tax_prd_yr"), "xml_url": xml_url})
        if filings:
            notes["filings_index"] = filings

        payload = {
            "ein": ein,
            "canonical_name": name,
            "funder_type": _infer_funder_type(subsection, ntee, foundation_code),
            "notes": notes,
        }
        return [(CorpusEventType.FUNDER_UPSERTED, payload)]


def _infer_funder_type(subsection: str, ntee: str, foundation_code: int | None) -> str:
    """Best-effort funder_type from IRS subsection + NTEE codes + ProPublica foundation_code.

    Priority order:
    1. subsection == '92'  — IRS BMF encoding for private foundations (highest confidence)
    2. foundation_code not in (None, 15)  — ProPublica: 3=operating PF, 4=non-operating PF;
       15 explicitly means 'not a private foundation'
    3. ntee starts with 'T3'  — NTEE community foundation code
    4. subsection in ('3', '03')  — 501(c)(3), public charity
    """
    if subsection == "92":
        return "private_foundation"
    if foundation_code is not None and foundation_code != 15:
        return "private_foundation"
    if ntee.startswith("T3"):
        return "community_foundation"
    if subsection in ("3", "03"):
        return "public_charity"
    return "unknown"


def _extract_object_id(pdf_url: str) -> str | None:
    """Extract IRS e-file object_id from a ProPublica pdf_url.

    ProPublica encodes e-filed documents as:
      .../download-filing?path=.../{EIN}_{period}_{FORMTYPE}_{object_id}.pdf

    The object_id is a 16-digit numeric string. Old pre-e-file URLs use a
    6-digit YYYYMM period code as the last component and return None.
    """
    try:
        parsed = urlparse(pdf_url)
        path = unquote(parse_qs(parsed.query).get("path", [""])[0])
        filename = path.rsplit("/", 1)[-1]
        stem = filename.rsplit(".", 1)[0]
        parts = stem.split("_")
        candidate = parts[-1] if parts else ""
        if candidate.isdigit() and len(candidate) >= 10:
            return candidate
    except Exception:
        pass
    return None
