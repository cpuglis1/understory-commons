"""DCAHAdapter — DC Commission on the Arts and Humanities (dcarts.dc.gov).

Two-pass fetch:
  Pass 1: GET index page, discover /grants/{slug} and /public-art/{slug} links.
  Pass 2: GET each detail page, emit OPPORTUNITY_SEEN, scan for native PDFs
          and fetch any found as secondary RawRecords.

The plan's expected RFA PDFs (FY27 cycle) are "scheduled for spring/summer 2026"
and were not yet posted at the time of source survey. The adapter scans for them
on each weekly run and picks them up automatically when posted.
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
from .http import RobotsBlocked
from .types import AdapterRunResult, FetchTask

logger = logging.getLogger(__name__)

_BASE_URL = "https://dcarts.dc.gov"
_FUNDER_NAME = "DC Commission on the Arts and Humanities"
_BASE_SUBJECT_AREAS = ["arts", "humanities"]


class DCAHAdapter(BaseAdapter):
    source_id: ClassVar[str] = "gov_dc_cah"
    version: ClassVar[str] = "0.1.0"
    rate_limit_per_sec: ClassVar[float] = 0.1  # Crawl-delay: 10 per robots.txt
    robots_compliance: ClassVar[str] = "strict"

    _INDEX_URL: ClassVar[str] = f"{_BASE_URL}/page/grant-programs"

    # Matches /grants/{slug} and /public-art/{slug} hrefs (relative or absolute).
    # Excludes the index itself (/grants/grant-programs).
    _DETAIL_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\'](?:https?://dcarts\.dc\.gov)?' r'(/(?:grants|public-art)/[^"\'?#]+)["\']',
        re.I,
    )
    _PDF_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\']((?:https?://dcarts\.dc\.gov)?/sites/default/files/[^"\']+\.pdf)["\']',
        re.I,
    )

    def __init__(self, store, event_log) -> None:
        super().__init__(store, event_log)
        self._detail_queue: list[str] = []
        self._pdf_queue: list[dict] = []

    def iter_fetch_tasks(self, **kwargs):
        yield FetchTask(url=self._INDEX_URL, expected_mime="text/html")

    def parse(self, raw: RawRecord) -> list:
        """Scan index page for detail links. No OPPORTUNITY_SEEN for the index itself."""
        body = self.store.get(raw.content_sha)
        seen: set[str] = set()
        for href in scan_hrefs(body, self._DETAIL_RE):
            # Skip the index page's self-reference
            if href.rstrip("/").endswith("/grant-programs"):
                continue
            url = href if href.startswith("http") else f"{_BASE_URL}{href}"
            if url not in seen:
                seen.add(url)
                self._detail_queue.append(url)
        return []

    def run(self, **kwargs) -> AdapterRunResult:
        result = super().run(**kwargs)

        # Pass 2: detail pages
        with httpx.Client(follow_redirects=True, headers=_DEFAULT_HEADERS) as client:
            for detail_url in self._detail_queue:
                self._fetch_detail(detail_url, client, result)

        # PDF attachments (when present on detail pages)
        if self._pdf_queue:
            with httpx.Client(follow_redirects=True, headers=_DEFAULT_HEADERS) as client:
                for item in self._pdf_queue:
                    fetch_attachment(
                        url=item["url"],
                        client=client,
                        adapter=self,
                        result=result,
                        parent_sha=item["parent_sha"],
                        parent_external_id=item["external_id"],
                        source_id=self.source_id,
                    )

        return result

    def _fetch_detail(
        self, detail_url: str, client: httpx.Client, result: AdapterRunResult
    ) -> None:
        task = FetchTask(url=detail_url, expected_mime="text/html")
        try:
            det_raw, det_is_new = self.fetch_one(task, client)
        except RobotsBlocked:
            result.robots_blocked += 1
            return
        except Exception as exc:
            logger.warning("Detail fetch failed for %s: %s", detail_url, exc)
            result.errors.append(str(exc))
            return

        result.fetched += 1
        if det_is_new:
            result.stored_new += 1

        body = self.store.get(det_raw.content_sha)
        title = extract_title(body)
        external_id = f"gov_dc_cah:{detail_url}"

        structured = build_structured_fields(body, title, _BASE_SUBJECT_AREAS)
        self.event_log.append(
            CorpusEventType.OPPORTUNITY_SEEN,
            content_sha=det_raw.content_sha,
            payload={
                "source_id": self.source_id,
                "external_id": external_id,
                "title": title,
                "funder_name_raw": _FUNDER_NAME,
                "content_sha": det_raw.content_sha,
                **structured,
            },
        )

        for href in scan_hrefs(body, self._PDF_RE):
            url = href if href.startswith("http") else f"{_BASE_URL}{href}"
            self._pdf_queue.append(
                {
                    "url": url,
                    "parent_sha": det_raw.content_sha,
                    "external_id": external_id,
                }
            )
