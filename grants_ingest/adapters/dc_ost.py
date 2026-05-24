"""DCOSTAdapter — DC Office of Out of School Time Grants (learn24.dc.gov).

Two-pass fetch:
  Pass 1: GET both index pages, scan for native learn24.dc.gov PDF links.
  Pass 2: Fetch each discovered PDF as a secondary RawRecord (50 MB cap),
          emit a second OPPORTUNITY_SEEN linking it to the parent index page.

Adobe Acrobat shared-document links (acrobat.adobe.com) are skipped —
they are ephemeral and not archivable via robots-compliant HTTP fetch.
Each skipped link is logged as OPPORTUNITY_FILTERED with
reason='external_link_unarchivable'.
"""

from __future__ import annotations

import logging
import re
from typing import ClassVar

import httpx

from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.raw_record import RawRecord

from .base import _DEFAULT_HEADERS, BaseAdapter
from .dc_html_util import build_structured_fields, extract_title, fetch_attachment, scan_hrefs
from .types import AdapterRunResult, FetchTask

logger = logging.getLogger(__name__)


class DCOSTAdapter(BaseAdapter):
    source_id: ClassVar[str] = "gov_dc_ost"
    version: ClassVar[str] = "0.1.0"
    rate_limit_per_sec: ClassVar[float] = 0.1  # Crawl-delay: 10 per robots.txt
    robots_compliance: ClassVar[str] = "strict"

    _INDEX_URLS: ClassVar[list[str]] = [
        "https://learn24.dc.gov/page/ost-office-grants",
        "https://learn24.dc.gov/page/funding-opportunities-0",
    ]
    _NATIVE_PDF_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\']((https?://learn24\.dc\.gov)?/sites/default/files/[^"\']+\.pdf)["\']',
        re.I,
    )
    _ACROBAT_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\']https?://acrobat\.adobe\.com/[^"\']*["\']',
        re.I,
    )
    _FUNDER_NAME: ClassVar[str] = "DC Office of Out of School Time Grants and Youth Outcomes"
    _BASE_SUBJECT_AREAS: ClassVar[list[str]] = [
        "youth_development",
        "education",
        "out_of_school_time",
    ]

    def __init__(self, store, event_log) -> None:
        super().__init__(store, event_log)
        self._pdf_queue: list[dict] = []

    def iter_fetch_tasks(self, **kwargs):
        for url in self._INDEX_URLS:
            yield FetchTask(url=url, expected_mime="text/html")

    def parse(self, raw: RawRecord) -> list:
        body = self.store.get(raw.content_sha)
        title = extract_title(body)
        external_id = f"gov_dc_ost:{raw.fetch_url}"

        # Queue native PDFs for pass 2
        for href in scan_hrefs(body, self._NATIVE_PDF_RE):
            url = href if href.startswith("http") else f"https://learn24.dc.gov{href}"
            self._pdf_queue.append(
                {"url": url, "index_sha": raw.content_sha, "external_id": external_id}
            )

        # Log skipped Acrobat links
        text = body.decode("utf-8", errors="ignore")
        acrobat_count = len(self._ACROBAT_RE.findall(text))
        if acrobat_count:
            self.event_log.append(
                CorpusEventType.OPPORTUNITY_FILTERED,
                content_sha=raw.content_sha,
                payload={
                    "source_id": self.source_id,
                    "reason": "external_link_unarchivable",
                    "external_host": "acrobat.adobe.com",
                    "count": acrobat_count,
                },
            )

        structured = build_structured_fields(body, title, self._BASE_SUBJECT_AREAS)
        return [
            (
                CorpusEventType.OPPORTUNITY_SEEN,
                {
                    "source_id": self.source_id,
                    "external_id": external_id,
                    "title": title,
                    "funder_name_raw": self._FUNDER_NAME,
                    "content_sha": raw.content_sha,
                    **structured,
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
