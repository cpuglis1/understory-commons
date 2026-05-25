"""CommunityFoundationGWCFAdapter — Greater Washington Community Foundation.

Source: thecommunityfoundation.org
Static HTML (Squarespace) — plain httpx, no Playwright needed.

Two-pass fetch:
  Pass 1: GET /open-grant-opportunities, discover /open-grant-opportunities/{slug}
          detail links. No OPPORTUNITY_SEEN emitted for the index itself.
  Pass 2: GET each detail page → emit OPPORTUNITY_SEEN with all extractable fields.
          Scan for natively-linked PDFs and fetch as secondary RawRecords.
"""

from __future__ import annotations

import logging
import re
from typing import ClassVar

import httpx

from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.extraction.structured import html_to_text
from grants_ingest.raw_record import RawRecord

from .base import _DEFAULT_HEADERS, BaseAdapter
from .dc_html_util import build_structured_fields, extract_title, fetch_attachment, scan_hrefs
from .http import RobotsBlocked
from .types import AdapterRunResult, FetchTask

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.thecommunityfoundation.org"
_FUNDER_NAME = "Greater Washington Community Foundation"
_BASE_SUBJECT_AREAS: list[str] = []
_DESCRIPTION_MAX_CHARS = 1500

_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.S | re.I)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.S | re.I)
_MAIN_RE = re.compile(r"<main[^>]*>(.*?)</main>", re.S | re.I)


class CommunityFoundationGWCFAdapter(BaseAdapter):
    source_id: ClassVar[str] = "cf_gwcf"
    version: ClassVar[str] = "0.1.0"
    rate_limit_per_sec: ClassVar[float] = 1 / 3  # 1 req / 3 s, courtesy limit
    robots_compliance: ClassVar[str] = "strict"

    _INDEX_URL: ClassVar[str] = f"{_BASE_URL}/open-grant-opportunities"

    # Matches /open-grant-opportunities/{slug} — relative or absolute, slug required.
    _DETAIL_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\']((?:https?://www\.thecommunityfoundation\.org)?'
        r"/open-grant-opportunities/[^\"'?#]+)[\"']",
        re.I,
    )

    # Known application portal domains captured into notes['apply_url'].
    _APPLY_URL_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\'](https?://[^"\']*'
        r"(?:grantrequest|submittable|foundant|fluxx|cybergrants|smapply|instrumentl)"
        r'[^"\']+)["\']',
        re.I,
    )

    # Any .pdf href — future-proof for natively-linked PDFs.
    _PDF_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\'](https?://[^"\']+\.pdf)["\']',
        re.I,
    )

    def __init__(self, store, event_log) -> None:
        super().__init__(store, event_log)
        self._detail_queue: list[str] = []
        self._pdf_queue: list[dict] = []

    def iter_fetch_tasks(self, **kwargs):
        yield FetchTask(url=self._INDEX_URL, expected_mime="text/html")

    def parse(self, raw: RawRecord) -> list:
        """Scan index for detail links. Returns [] — no OPPORTUNITY_SEEN for the index."""
        body = self.store.get(raw.content_sha)
        seen: set[str] = set()
        for href in scan_hrefs(body, self._DETAIL_RE):
            url = href if href.startswith("http") else f"{_BASE_URL}{href}"
            if url not in seen:
                seen.add(url)
                self._detail_queue.append(url)
        return []

    def run(self, **kwargs) -> AdapterRunResult:
        result = super().run(**kwargs)

        with httpx.Client(follow_redirects=True, headers=_DEFAULT_HEADERS) as client:
            for detail_url in self._detail_queue:
                self._fetch_detail(detail_url, client, result)

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
        # Squarespace titles use em-dash separator: "Title — Greater Washington CF"
        title = extract_title(body, sep=" — ")
        external_id = f"cf_gwcf:{detail_url}"

        structured = build_structured_fields(body, title, _BASE_SUBJECT_AREAS)

        notes: dict = {}

        raw_html = body.decode("utf-8", errors="ignore")
        apply_m = self._APPLY_URL_RE.search(raw_html)
        if apply_m:
            notes["apply_url"] = apply_m.group(1)

        # Extract description from <main> to skip Squarespace nav boilerplate,
        # then strip script/style remnants before converting to plain text.
        main_m = _MAIN_RE.search(raw_html)
        content_html = main_m.group(1) if main_m else raw_html
        clean_html = _SCRIPT_RE.sub("", _STYLE_RE.sub("", content_html))
        description = html_to_text(clean_html.encode())[:_DESCRIPTION_MAX_CHARS].strip()
        if description:
            notes["description"] = description

        self.event_log.append(
            CorpusEventType.OPPORTUNITY_SEEN,
            content_sha=det_raw.content_sha,
            payload={
                "source_id": self.source_id,
                "external_id": external_id,
                "title": title,
                "funder_name_raw": _FUNDER_NAME,
                "content_sha": det_raw.content_sha,
                "notes": notes,
                **structured,
            },
        )

        for href in scan_hrefs(body, self._PDF_RE):
            self._pdf_queue.append(
                {
                    "url": href,
                    "parent_sha": det_raw.content_sha,
                    "external_id": external_id,
                }
            )
