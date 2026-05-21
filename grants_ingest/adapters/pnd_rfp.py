"""PNDRfpAdapter — Philanthropy News Digest RFP feed.

Two-pass run (overrides BaseAdapter.run):
  Pass 1: fetch the RSS feed, parse all items, apply geo pre-filter.
           Emit OPPORTUNITY_SEEN for passing items, OPPORTUNITY_FILTERED for
           failing ones. Record per-item source URLs for pass 2.
  Pass 2: for each passing item, fetch the linked funder source page and
           store it as a second RawRecord on the same OpportunityInstance.

The two-pass approach is documented as a per-adapter run() override per plan
§Q3 decision. If a second two-pass adapter appears in slice 4, lift the pattern
to a base-class iter_fetch_tasks_followup() hook at that point.
"""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import ClassVar

import httpx

from grants_ingest.corpus_event import CorpusEventType

from .base import _DEFAULT_HEADERS, BaseAdapter
from .http import RobotsBlocked
from .types import AdapterRunResult, FetchTask

logger = logging.getLogger(__name__)

DEFAULT_RSS_URL = "https://philanthropynewsdigest.org/rfps/rss"

# Tokens that pass the geographic pre-filter (case-insensitive substring match)
_GEO_PASS_TOKENS = [
    "national",
    "dc",
    "district of columbia",
    "md",
    "maryland",
    "va",
    "virginia",
    "dmv",
]

# Deadline patterns in PND item descriptions
_DEADLINE_RE = re.compile(r"deadline[:\s]+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE)

# Funder name patterns
_FUNDER_RE = re.compile(r"funder[:\s]+([^.]+)\.", re.IGNORECASE)


class PNDRfpAdapter(BaseAdapter):
    source_id: ClassVar[str] = "pnd_rfp"
    version: ClassVar[str] = "0.1.0"
    rate_limit_per_sec: ClassVar[float] = 1.0
    robots_compliance: ClassVar[str] = "strict"

    def __init__(self, store, event_log, rss_url: str = DEFAULT_RSS_URL) -> None:
        super().__init__(store, event_log)
        self.rss_url = rss_url

    def iter_fetch_tasks(self, **kwargs):
        yield FetchTask(url=self.rss_url, expected_mime="application/rss+xml")

    def run(self, **kwargs) -> AdapterRunResult:
        result = AdapterRunResult(source_id=self.source_id)
        with httpx.Client(follow_redirects=True, headers=_DEFAULT_HEADERS) as client:
            # Pass 1: fetch RSS and parse items
            rss_task = FetchTask(url=self.rss_url, expected_mime="application/rss+xml")
            try:
                rss_raw, is_new = self.fetch_one(rss_task, client)
            except RobotsBlocked:
                result.robots_blocked += 1
                return result
            except Exception as exc:
                logger.error("Error fetching PND RSS: %s", exc)
                result.errors.append(str(exc))
                return result

            result.fetched += 1
            if is_new:
                result.stored_new += 1

            try:
                passing_items = self._parse_rss(rss_raw, result)
            except Exception as exc:
                logger.error("Error parsing PND RSS: %s", exc)
                result.parse_errors += 1
                result.errors.append(str(exc))
                return result

            # Pass 2: fetch source pages for passing items
            for item in passing_items:
                source_url = item.get("source_page_url")
                if not source_url:
                    continue
                source_task = FetchTask(
                    url=source_url,
                    expected_mime="text/html",
                    extra_metadata={"pnd_guid": item["pnd_guid"]},
                )
                try:
                    source_raw, src_is_new = self.fetch_one(source_task, client)
                except RobotsBlocked:
                    result.robots_blocked += 1
                    continue
                except Exception as exc:
                    logger.error("Error fetching PND source page %s: %s", source_url, exc)
                    result.errors.append(str(exc))
                    continue

                result.fetched += 1
                if src_is_new:
                    result.stored_new += 1

                # Update OPPORTUNITY_SEEN event payload with source-page SHA
                # so the materializer can M2M-link the source page RawRecord.
                # We emit a lightweight OPPORTUNITY_UPDATED event that carries
                # the extra_content_sha.
                self.event_log.append(
                    CorpusEventType.OPPORTUNITY_SEEN,
                    content_sha=rss_raw.content_sha,
                    payload={
                        **item,
                        "extra_content_shas": [source_raw.content_sha],
                    },
                )

        return result

    def _parse_rss(self, rss_raw, result: AdapterRunResult) -> list[dict]:
        """Parse RSS body, emit events for each item. Return list of passing items."""
        from grants_ingest.corpus_event import CorpusEvent

        body = _sanitize_rss_xml(self.store.get(rss_raw.content_sha))
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise ValueError(f"RSS parse error: {exc}") from exc

        channel = root.find("channel")
        if channel is None:
            raise ValueError("RSS: no <channel> element found")

        dc_ns = "http://purl.org/dc/elements/1.1/"
        seen_guids_this_run: set[str] = set()
        passing_items: list[dict] = []

        for item_el in channel.findall("item"):
            guid = (item_el.findtext("guid") or "").strip()
            title = (item_el.findtext("title") or "").strip()
            link = (item_el.findtext("link") or "").strip()
            description = (item_el.findtext("description") or "").strip()
            pub_date_str = item_el.findtext("pubDate") or item_el.findtext(f"{{{dc_ns}}}date")
            first_seen_at = _parse_pub_date(pub_date_str)
            close_date = _extract_deadline(description)
            funder_name_raw = _extract_funder(description)
            geo_text = _extract_geo(description)

            if not guid:
                guid = link  # fall back to URL as GUID

            # Dedup within this run
            if guid in seen_guids_this_run:
                continue
            seen_guids_this_run.add(guid)

            external_id = f"pnd_rfp:{guid}"

            # Geo pre-filter
            if not _passes_geo_filter(geo_text):
                self.event_log.append(
                    CorpusEventType.OPPORTUNITY_FILTERED,
                    content_sha=rss_raw.content_sha,
                    payload={
                        "source_id": self.source_id,
                        "title": title,
                        "geo_scope_text": geo_text,
                        "reason": "geo_filter",
                        "pnd_guid": guid,
                    },
                )
                continue

            # Check if we've seen this GUID before with the same close date
            prior_event = (
                CorpusEvent.objects.filter(
                    source_id=self.source_id,
                    event_type__in=[
                        CorpusEventType.OPPORTUNITY_SEEN,
                        CorpusEventType.OPPORTUNITY_UPDATED,
                    ],
                    payload__external_id=external_id,
                )
                .order_by("-id")
                .first()
            )

            item_payload: dict = {
                "source_id": self.source_id,
                "external_id": external_id,
                "title": title,
                "funder_name_raw": funder_name_raw,
                "notes": {
                    "pnd_guid": guid,
                    "source_page_url": link,
                    "pnd_summary": description,
                },
                "geographic_scope": {"raw_text": geo_text},
                "source_page_url": link,
                "pnd_guid": guid,
                "content_sha": rss_raw.content_sha,
            }
            if first_seen_at:
                item_payload["first_seen_at"] = first_seen_at.isoformat()
            if close_date:
                item_payload["application_close_at"] = close_date.isoformat()

            if prior_event:
                prior_close = prior_event.payload.get("application_close_at")
                if prior_close != item_payload.get("application_close_at"):
                    # Deadline changed — emit OPPORTUNITY_UPDATED
                    self.event_log.append(
                        CorpusEventType.OPPORTUNITY_UPDATED,
                        content_sha=rss_raw.content_sha,
                        payload=item_payload,
                    )
                # Either way, don't emit a second OPPORTUNITY_SEEN
                # but do fetch the source page again (it may have changed)
                passing_items.append(item_payload)
            else:
                self.event_log.append(
                    CorpusEventType.OPPORTUNITY_SEEN,
                    content_sha=rss_raw.content_sha,
                    payload=item_payload,
                )
                passing_items.append(item_payload)

        return passing_items


_XML_BUILTIN_ENTITIES = frozenset({"amp", "lt", "gt", "quot", "apos"})
_NAMED_ENTITY_RE = re.compile(r"&([a-zA-Z][a-zA-Z0-9]*);")


def _sanitize_rss_xml(body: bytes) -> bytes:
    """Replace undefined HTML named entities with their unicode equivalents.

    ElementTree only understands the 5 XML built-in entities. PND RSS uses
    HTML named entities (e.g. &ldquo; &rsquo;). This pass converts them to
    plain unicode before handing the bytes to ElementTree.
    """

    def _replace(m: re.Match) -> str:
        name = m.group(1)
        if name in _XML_BUILTIN_ENTITIES:
            return m.group(0)
        return html.unescape(m.group(0))

    text = body.decode("utf-8", errors="replace")
    return _NAMED_ENTITY_RE.sub(_replace, text).encode("utf-8")


def _passes_geo_filter(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(token in lower for token in _GEO_PASS_TOKENS)


def _extract_geo(description: str) -> str:
    """Extract geographic focus text from PND item description."""
    lower = description.lower()
    for pattern in [
        r"geographic focus[:\s]+([^.]+)\.",
        r"geographic scope[:\s]+([^.]+)\.",
        r"geography[:\s]+([^.]+)\.",
    ]:
        m = re.search(pattern, lower)
        if m:
            return m.group(1).strip()
    # Fall back: look for known geo tokens in the description itself
    found = [t for t in _GEO_PASS_TOKENS if t in lower]
    return " ".join(found) if found else ""


def _extract_deadline(description: str) -> datetime | None:
    m = _DEADLINE_RE.search(description)
    if not m:
        return None
    raw = m.group(1).strip().rstrip(",")
    for fmt in ("%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _extract_funder(description: str) -> str:
    m = _FUNDER_RE.search(description)
    if m:
        return m.group(1).strip()
    return ""


def _parse_pub_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    # Try RFC 2822 (RSS standard)
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(UTC)
    except Exception:
        pass
    # Try ISO date (dc:date)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
