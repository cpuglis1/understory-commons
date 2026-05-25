"""Shared HTML parsing utilities for DC grant portal adapters (gov_dc_*, dc_*)."""

from __future__ import annotations

import html
import logging
import re

import httpx

from grants_ingest.corpus_event import CorpusEventType

from .http import RobotsBlocked
from .types import AdapterRunResult, FetchTask

logger = logging.getLogger(__name__)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_PDF_SIZE_CAP = 50 * 1024 * 1024


def extract_title(body: bytes, sep: str = " | ") -> str:
    """Extract <title> text from raw HTML, stripping the trailing ' | sitename' suffix."""
    m = _TITLE_RE.search(body.decode("utf-8", errors="ignore"))
    if not m:
        return ""
    title = html.unescape(m.group(1)).strip()
    if sep and sep in title:
        title = title.rsplit(sep, 1)[0].strip()
    return title


def scan_hrefs(body: bytes, pattern: re.Pattern) -> list[str]:
    """Return all href values from raw HTML bytes where pattern group 1 matches."""
    text = body.decode("utf-8", errors="ignore")
    return [m.group(1) for m in pattern.finditer(text)]


# Canonical DC agency names keyed by abbreviation used in MOCA NOFA titles.
DC_AGENCY_NAMES: dict[str, str] = {
    "OSSE": "DC Office of the State Superintendent of Education",
    "DOES": "DC Department of Employment Services",
    "DHS": "DC Department of Human Services",
    "DBH": "DC Department of Behavioral Health",
    "DC Health": "DC Department of Health",
    "DDOT": "DC Department of Transportation",
    "DMPED": "DC Office of Planning and Economic Development",
    "DHCD": "DC Department of Housing and Community Development",
    "OVSJG": "DC Office of Victim Services and Justice Grants",
    "ONSE": "DC Office of Neighborhood Safety and Engagement",
    "DMPSJ": "DC Office of Migrant Services and Public Health Justice",
    "DPR": "DC Department of Parks and Recreation",
    "OAG": "DC Office of the Attorney General",
    "MPD": "DC Metropolitan Police Department",
}

# Build once; order matters — longer keys before substrings (DC Health before DHS).
_AGENCY_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in DC_AGENCY_NAMES) + r")\b")


def extract_moca_agency(title: str) -> str | None:
    """Return canonical agency name from a MOCA NOFA title, or None if unrecognized."""
    m = _AGENCY_RE.search(title)
    if not m:
        return None
    return DC_AGENCY_NAMES[m.group(1)]


def fetch_attachment(
    url: str,
    client: httpx.Client,
    adapter,
    result: AdapterRunResult,
    parent_sha: str,
    parent_external_id: str,
    source_id: str,
    expected_mime: str = "application/pdf",
) -> None:
    """Fetch a PDF/DOCX attachment, store content-addressed, emit OPPORTUNITY_SEEN link."""
    try:
        head = client.head(url, timeout=15)
        content_length = int(head.headers.get("content-length", 0))
        if content_length > _PDF_SIZE_CAP:
            logger.warning("Attachment %s too large (%d bytes), skipping", url, content_length)
            adapter.event_log.append(
                CorpusEventType.OPPORTUNITY_FILTERED,
                payload={"url": url, "reason": "pdf_too_large", "source_id": source_id},
            )
            return
    except Exception:
        pass  # HEAD failed — proceed; 50MB cap enforced by object store

    task = FetchTask(url=url, expected_mime=expected_mime)
    try:
        att_raw, att_is_new = adapter.fetch_one(task, client)
    except RobotsBlocked:
        result.robots_blocked += 1
        return
    except Exception as exc:
        logger.warning("Attachment fetch failed for %s: %s", url, exc)
        result.errors.append(str(exc))
        return

    result.fetched += 1
    if att_is_new:
        result.stored_new += 1

    adapter.event_log.append(
        CorpusEventType.OPPORTUNITY_SEEN,
        content_sha=parent_sha,
        payload={
            "source_id": source_id,
            "external_id": parent_external_id,
            "extra_content_shas": [att_raw.content_sha],
        },
    )
