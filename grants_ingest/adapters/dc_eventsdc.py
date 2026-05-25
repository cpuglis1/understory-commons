"""DCEventsDCAdapter — Events DC Community Grants (eventsdc.com).

One-pass + PDF fetch:
  Pass 1: GET /community/community-grants, emit one OPPORTUNITY_SEEN for
          the index page, scan for /sites/default/files/*.pdf links.
  Pass 2: Fetch each discovered PDF as a secondary RawRecord.

Events DC is the Washington Convention and Sports Authority, a DC
instrumentality (per DC Code §10-1202.01) — a quasi-public funder
distributing public DC funds. funder_type = govt_local (no quasi_govt
enum value exists yet; notes['quasi_public'] preserves the distinction
on the eventual Funder row, set by the materializer/resolver). The
SmartSimple application portal is embedded in the index page itself
(no external apply_url to capture).
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

_BASE_URL = "https://eventsdc.com"
_FUNDER_NAME = "Events DC"


class DCEventsDCAdapter(BaseAdapter):
    source_id: ClassVar[str] = "dc_eventsdc"
    version: ClassVar[str] = "0.1.0"
    rate_limit_per_sec: ClassVar[float] = 1.0  # robots.txt has no Crawl-delay; 1 req/s courtesy
    robots_compliance: ClassVar[str] = "strict"

    _INDEX_URL: ClassVar[str] = f"{_BASE_URL}/community/community-grants"

    _PDF_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\']((?:https?://eventsdc\.com)?/sites/default/files/[^"\']+\.pdf)["\']',
        re.I,
    )

    def __init__(self, store, event_log) -> None:
        super().__init__(store, event_log)
        self._pdf_queue: list[dict] = []

    def iter_fetch_tasks(self, **kwargs):
        yield FetchTask(url=self._INDEX_URL, expected_mime="text/html")

    def parse(self, raw: RawRecord) -> list:
        body = self.store.get(raw.content_sha)
        title = extract_title(body)
        external_id = f"dc_eventsdc:{raw.fetch_url}"

        for href in scan_hrefs(body, self._PDF_RE):
            url = href if href.startswith("http") else f"{_BASE_URL}{href}"
            self._pdf_queue.append(
                {"url": url, "index_sha": raw.content_sha, "external_id": external_id}
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
