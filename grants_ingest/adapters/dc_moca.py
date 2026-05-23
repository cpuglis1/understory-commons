"""DCMOCAAdapter — DC MOCA multi-agency grants clearinghouse (communityaffairs.dc.gov).

Three-pass fetch:
  Pass 1: GET index page, discover /publication/* links.
  Pass 2: GET each publication page, emit OPPORTUNITY_SEEN, discover attachment links.
  Pass 3: Fetch each attachment (PDF/DOCX) as a secondary RawRecord.

MOCA is a clearinghouse, not a funder. Each NOFA's issuing agency is extracted
from the publication page title using extract_moca_agency(). If the agency
abbreviation is not recognized, funder_name_raw falls back to
'DC Government (agency unresolved)' and the record lands in the manual-review queue.
"""

from __future__ import annotations

import logging
import re
from typing import ClassVar

import httpx

from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.raw_record import RawRecord

from .base import _DEFAULT_HEADERS, BaseAdapter
from .dc_html_util import extract_moca_agency, extract_title, fetch_attachment, scan_hrefs
from .http import RobotsBlocked
from .types import AdapterRunResult, FetchTask

logger = logging.getLogger(__name__)

_BASE_URL = "https://communityaffairs.dc.gov"
_FALLBACK_FUNDER = "DC Government (agency unresolved)"


class DCMOCAAdapter(BaseAdapter):
    source_id: ClassVar[str] = "gov_dc_moca"
    version: ClassVar[str] = "0.1.0"
    rate_limit_per_sec: ClassVar[float] = 0.1  # Crawl-delay: 10 per robots.txt
    robots_compliance: ClassVar[str] = "strict"

    _INDEX_URL: ClassVar[str] = f"{_BASE_URL}/content/community-grant-program"

    # Matches /publication/{slug} hrefs (relative or absolute on same domain)
    _PUBLICATION_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\'](?:https?://communityaffairs\.dc\.gov)?(/publication/[^"\'?#]+)["\']',
        re.I,
    )
    # Matches native attachment URLs (PDF or DOCX)
    _ATTACHMENT_RE: ClassVar[re.Pattern] = re.compile(
        r'href=["\']'
        r"(?:https?://communityaffairs\.dc\.gov)?"
        r'(/sites/moca/files/[^"\'?#]+\.(pdf|docx))'
        r'["\']',
        re.I,
    )

    def __init__(self, store, event_log) -> None:
        super().__init__(store, event_log)
        self._publication_queue: list[str] = []
        self._attachment_queue: list[dict] = []

    def iter_fetch_tasks(self, **kwargs):
        yield FetchTask(url=self._INDEX_URL, expected_mime="text/html")

    def parse(self, raw: RawRecord) -> list:
        """Scan index page for publication links. No OPPORTUNITY_SEEN for the index itself."""
        body = self.store.get(raw.content_sha)
        seen: set[str] = set()
        for href in scan_hrefs(body, self._PUBLICATION_RE):
            url = f"{_BASE_URL}{href}" if not href.startswith("http") else href
            if url not in seen:
                seen.add(url)
                self._publication_queue.append(url)
        return []

    def run(self, **kwargs) -> AdapterRunResult:
        result = super().run(**kwargs)

        # Pass 2: publication pages
        with httpx.Client(follow_redirects=True, headers=_DEFAULT_HEADERS) as client:
            for pub_url in self._publication_queue:
                self._fetch_publication(pub_url, client, result)

        # Pass 3: attachments
        with httpx.Client(follow_redirects=True, headers=_DEFAULT_HEADERS) as client:
            for item in self._attachment_queue:
                fetch_attachment(
                    url=item["url"],
                    client=client,
                    adapter=self,
                    result=result,
                    parent_sha=item["pub_sha"],
                    parent_external_id=item["external_id"],
                    source_id=self.source_id,
                    expected_mime=item["mime"],
                )

        return result

    def _fetch_publication(
        self, pub_url: str, client: httpx.Client, result: AdapterRunResult
    ) -> None:
        task = FetchTask(url=pub_url, expected_mime="text/html")
        try:
            pub_raw, pub_is_new = self.fetch_one(task, client)
        except RobotsBlocked:
            result.robots_blocked += 1
            return
        except Exception as exc:
            logger.warning("Publication fetch failed for %s: %s", pub_url, exc)
            result.errors.append(str(exc))
            return

        result.fetched += 1
        if pub_is_new:
            result.stored_new += 1

        body = self.store.get(pub_raw.content_sha)
        title = extract_title(body)
        funder_name_raw = extract_moca_agency(title) or _FALLBACK_FUNDER
        external_id = f"gov_dc_moca:{pub_url}"

        self.event_log.append(
            CorpusEventType.OPPORTUNITY_SEEN,
            content_sha=pub_raw.content_sha,
            payload={
                "source_id": self.source_id,
                "external_id": external_id,
                "title": title,
                "funder_name_raw": funder_name_raw,
                "content_sha": pub_raw.content_sha,
            },
        )

        # Queue attachments found on this publication page
        for href in scan_hrefs(body, self._ATTACHMENT_RE):
            url = f"{_BASE_URL}{href}" if not href.startswith("http") else href
            ext = href.rsplit(".", 1)[-1].lower()
            mime = (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if ext == "docx"
                else "application/pdf"
            )
            self._attachment_queue.append(
                {
                    "url": url,
                    "pub_sha": pub_raw.content_sha,
                    "external_id": external_id,
                    "mime": mime,
                }
            )
