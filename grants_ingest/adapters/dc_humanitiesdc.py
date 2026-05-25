"""DCHumanitiesDCAdapter — HumanitiesDC grant programs (humanitiesdc.org).

Two-pass fetch:
  Pass 1: GET /grant-opportunities, emit one OPPORTUNITY_SEEN for the
          index page (per plan §6 Q2 recommendation — Component 2 splits
          per-program rows), scan for wp-content/uploads/*.pdf links.
  Pass 2: Fetch each discovered PDF as a secondary RawRecord.

HumanitiesDC is a federally chartered 501(c)(3) humanities council (funded
by CAH and NEH); funder_type = public_charity, not govt_local. The
GrantInterface application portal URL is captured in notes['apply_url'].
"""

from __future__ import annotations

import logging
import re
from typing import ClassVar

import httpx

from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.raw_record import RawRecord

from .base import _DEFAULT_HEADERS, BaseAdapter
from .dc_html_util import extract_title, fetch_attachment, scan_hrefs
from .types import AdapterRunResult, FetchTask

logger = logging.getLogger(__name__)

_BASE_URL = "https://humanitiesdc.org"
_FUNDER_NAME = "HumanitiesDC"
_APPLY_PORTAL_URL = "https://www.grantinterface.com/Home/Logon?urlkey=wdchumanities"


class DCHumanitiesDCAdapter(BaseAdapter):
    source_id: ClassVar[str] = "dc_humanitiesdc"
    version: ClassVar[str] = "0.1.0"
    rate_limit_per_sec: ClassVar[float] = 1.0  # robots.txt allows full access; courtesy 1 req/s
    robots_compliance: ClassVar[str] = "strict"

    _INDEX_URL: ClassVar[str] = f"{_BASE_URL}/grant-opportunities"

    _PDF_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\'](https?://humanitiesdc\.org/wp-content/uploads/[^"\']+\.pdf)["\']',
        re.I,
    )

    def __init__(self, store, event_log) -> None:
        super().__init__(store, event_log)
        self._pdf_queue: list[dict] = []

    def iter_fetch_tasks(self, **kwargs):
        yield FetchTask(url=self._INDEX_URL, expected_mime="text/html")

    def parse(self, raw: RawRecord) -> list:
        body = self.store.get(raw.content_sha)
        title = extract_title(body, sep=" - ")
        external_id = f"dc_humanitiesdc:{raw.fetch_url}"

        for href in scan_hrefs(body, self._PDF_RE):
            self._pdf_queue.append(
                {"url": href, "index_sha": raw.content_sha, "external_id": external_id}
            )

        return [
            (
                CorpusEventType.OPPORTUNITY_SEEN,
                {
                    "source_id": self.source_id,
                    "external_id": external_id,
                    "title": title,
                    "funder_name_raw": _FUNDER_NAME,
                    "content_sha": raw.content_sha,
                    "notes": {"apply_url": _APPLY_PORTAL_URL},
                },
            )
        ]

    def run(self, **kwargs) -> AdapterRunResult:
        result = super().run(**kwargs)
        if self._pdf_queue:
            with httpx.Client(follow_redirects=True, headers=_DEFAULT_HEADERS) as client:
                for item in self._pdf_queue:
                    fetch_attachment(
                        url=item["url"],
                        client=client,
                        adapter=self,
                        result=result,
                        parent_sha=item["index_sha"],
                        parent_external_id=item["external_id"],
                        source_id=self.source_id,
                    )
        return result
