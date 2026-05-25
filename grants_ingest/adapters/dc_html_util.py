"""Shared HTML parsing utilities for DC grant portal adapters (gov_dc_*, dc_*)."""

from __future__ import annotations

import html
import logging
import re
from datetime import UTC
from typing import Any

import httpx
from django.utils import timezone

from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.extraction.structured import (
    AGENCY_SUBJECT_AREAS,
    augment_subject_areas_from_title,
    extract_award_range,
    extract_budget_cap,
    extract_deadline,
    extract_org_type,
    extract_status,
    html_to_text,
)

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


def build_structured_fields(
    body: bytes,
    title: str,
    base_subject_areas: list[str],
    *,
    check_budget_cap: bool = False,
    agency_for_subject_areas: str | None = None,
) -> dict[str, Any]:
    """Run deterministic extractors on page body and return OPPORTUNITY_SEEN payload fields.

    Only non-None values are included so callers can safely merge with the
    existing payload dict without overwriting existing fields with None.

    Args:
        body: Raw HTML bytes.
        title: Opportunity title (used for keyword augmentation).
        base_subject_areas: Source-level default subject area codes.
        check_budget_cap: If True, attempt to extract budget eligibility cap
            (used by dc_humanitiesdc where "under $2M budget" is common).
        agency_for_subject_areas: If not None, look up AGENCY_SUBJECT_AREAS to
            augment subject_areas (used by gov_dc_moca after agency attribution).
    """
    text = html_to_text(body)
    now = timezone.now().replace(tzinfo=None)

    fields: dict[str, Any] = {}

    # Deadline / status
    deadline = extract_deadline(body, text)
    if deadline is not None:
        # Deadline dates are end-of-day on a local DC date; store as UTC-aware.
        deadline_aware = deadline.replace(tzinfo=UTC)
        fields["application_close_at"] = deadline_aware.isoformat()
        fields["status"] = extract_status(deadline, now)
    else:
        fields["status"] = "open"

    # Award range
    award_min, award_max = extract_award_range(body, text)
    if award_min is not None:
        fields["award_min"] = str(award_min)
    if award_max is not None:
        fields["award_max"] = str(award_max)

    # Org type -> eligibility dict
    org_type = extract_org_type(body, text)
    eligibility: dict[str, Any] = {}
    if org_type:
        eligibility["org_type"] = org_type

    if check_budget_cap:
        cap = extract_budget_cap(text)
        if cap is not None:
            eligibility["budget_max"] = int(cap)

    if eligibility:
        fields["eligibility"] = eligibility

    # Subject areas: base + agency override + title keywords
    subject_areas = list(base_subject_areas)
    if agency_for_subject_areas:
        agency_codes = AGENCY_SUBJECT_AREAS.get(agency_for_subject_areas, [])
        for code in agency_codes:
            if code not in subject_areas:
                subject_areas.append(code)
    subject_areas = augment_subject_areas_from_title(title, subject_areas)
    if subject_areas:
        fields["subject_areas"] = subject_areas

    return fields
