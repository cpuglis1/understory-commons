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

        org = data.get("organization") or data
        if not org:
            return []

        ein = str(org.get("ein", "")).replace("-", "") or None
        name = org.get("name", "")
        ntee = org.get("ntee_code") or ""
        subsection = str(org.get("subsection_code") or org.get("subseccd") or "")

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

        # Store the filings index for the irs_990pf adapter to consume
        filings = [
            {
                "year": f.get("tax_prd_yr"),
                "xml_url": f.get("formtype_url") or f.get("pdf"),
            }
            for f in data.get("filings_with_data", [])
            if f.get("formtype_url") or f.get("pdf")
        ]
        if filings:
            notes["filings_index"] = filings

        payload = {
            "ein": ein,
            "canonical_name": name,
            "funder_type": _infer_funder_type(subsection, ntee),
            "notes": notes,
        }
        return [(CorpusEventType.FUNDER_UPSERTED, payload)]


def _infer_funder_type(subsection: str, ntee: str) -> str:
    """Best-effort funder_type from IRS subsection + NTEE codes."""
    if subsection == "92":
        return "private_foundation"
    if ntee.startswith("T3"):
        return "community_foundation"
    if subsection in ("3", "03"):
        return "public_charity"
    return "unknown"
