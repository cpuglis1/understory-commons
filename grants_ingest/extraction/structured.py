"""Deterministic field extraction for Tier B/C DC grant pages.

Each function returns a value if confidently extractable, None otherwise.
None is never a failure — it means "defer to Component 2."
All functions are safe to call on any input; they never raise.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DC agency taxonomy
# Maps short abbreviation/keyword -> canonical agency name.
# Used by extract_dc_agency() to search full page body text, not just titles.
# Keys are ordered longest-first to avoid substring false positives at regex build.
# ---------------------------------------------------------------------------
DC_AGENCY_TAXONOMY: dict[str, str] = {
    "Office of the State Superintendent of Education": "DC Office of the State Superintendent of Education",
    "State Superintendent of Education": "DC Office of the State Superintendent of Education",
    "Department of Employment Services": "DC Department of Employment Services",
    "Department of Human Services": "DC Department of Human Services",
    "Department of Behavioral Health": "DC Department of Behavioral Health",
    "Department of Health": "DC Department of Health",
    "Department of Transportation": "DC Department of Transportation",
    "Office of Planning and Economic Development": "DC Office of Planning and Economic Development",
    "Department of Housing and Community Development": "DC Department of Housing and Community Development",
    "Office of Victim Services and Justice Grants": "DC Office of Victim Services and Justice Grants",
    "Office of Neighborhood Safety and Engagement": "DC Office of Neighborhood Safety and Engagement",
    "Department of Parks and Recreation": "DC Department of Parks and Recreation",
    "Office of the Attorney General": "DC Office of the Attorney General",
    "Metropolitan Police Department": "DC Metropolitan Police Department",
    # Abbreviations (shorter, must come after full names in regex alternation)
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
    "DPR": "DC Department of Parks and Recreation",
    "OAG": "DC Office of the Attorney General",
    "MPD": "DC Metropolitan Police Department",
}

# Agency canonical name -> subject_area codes it typically funds.
# Used by gov_dc_moca to augment subject_areas once an agency is identified.
AGENCY_SUBJECT_AREAS: dict[str, list[str]] = {
    "DC Office of the State Superintendent of Education": ["education"],
    "DC Department of Employment Services": ["workforce"],
    "DC Department of Human Services": ["human_services"],
    "DC Department of Behavioral Health": ["behavioral_health", "mental_health"],
    "DC Department of Health": ["health"],
    "DC Department of Transportation": ["transportation"],
    "DC Office of Planning and Economic Development": ["economic_development"],
    "DC Department of Housing and Community Development": ["housing"],
    "DC Office of Victim Services and Justice Grants": ["public_safety"],
    "DC Office of Neighborhood Safety and Engagement": ["public_safety", "youth_development"],
    "DC Department of Parks and Recreation": ["youth_development", "arts", "athletics"],
    "DC Office of the Attorney General": ["public_safety"],
    "DC Metropolitan Police Department": ["public_safety"],
}

# Regex built once from taxonomy keys, longest keys first to avoid substring matches.
_TAXONOMY_KEYS_SORTED = sorted(DC_AGENCY_TAXONOMY.keys(), key=len, reverse=True)
_AGENCY_BODY_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _TAXONOMY_KEYS_SORTED) + r")\b",
    re.I,
)

# ---------------------------------------------------------------------------
# Title keyword -> subject_area codes to add
# ---------------------------------------------------------------------------
_TITLE_KEYWORD_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bSTEM\b", re.I), "stem"),
    (re.compile(r"\b(?:science|technology|engineering|mathematics?|math)\b", re.I), "stem"),
    (re.compile(r"\b(?:literacy|reading|writing|language arts)\b", re.I), "literacy"),
    (re.compile(r"\b(?:mentor(?:ing|ship)?|tutoring?|coaching)\b", re.I), "mentorship"),
    (re.compile(r"\b(?:workforce|employment|job training|vocational|career)\b", re.I), "workforce"),
    (
        re.compile(r"\b(?:mental health|trauma|counseling|behavioral health)\b", re.I),
        "mental_health",
    ),
    (
        re.compile(r"\b(?:arts? education|arts? program|visual arts?|performing arts?)\b", re.I),
        "arts_education",
    ),
    (re.compile(r"\b(?:music|theater|theatre|dance|visual art|public art)\b", re.I), "arts"),
    (re.compile(r"\b(?:humanities|history|culture|cultural)\b", re.I), "humanities"),
    (
        re.compile(r"\b(?:youth development|out.of.school|after.?school|OST)\b", re.I),
        "youth_development",
    ),
    (re.compile(r"\b(?:early childhood|pre-?k|preschool|head start)\b", re.I), "early_childhood"),
    (re.compile(r"\b(?:food|nutrition|hunger|meals?)\b", re.I), "food_security"),
    (re.compile(r"\b(?:housing|shelter|homeless)\b", re.I), "housing"),
    (re.compile(r"\b(?:environment|green|sustainability|climate)\b", re.I), "environment"),
    (re.compile(r"\b(?:sport|athletic|recreation|fitness)\b", re.I), "athletics"),
]

# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_ABBR = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")

# "March 15, 2026" or "March 15 2026"
_DATE_LONG_RE = re.compile(
    r"\b(?:" + "|".join(_MONTH_NAMES) + r")\s+(\d{1,2}),?\s+(\d{4})\b",
    re.I,
)
# "Mar. 15, 2026" or "Mar 15, 2026"
_DATE_ABBR_RE = re.compile(
    r"\b(?:" + "|".join(_MONTH_ABBR) + r")\.?\s+(\d{1,2}),?\s+(\d{4})\b",
    re.I,
)
# "05/31/2026" or "5/31/2026"
_DATE_SLASH_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")

# Context words that indicate the following date is a deadline
_DEADLINE_CONTEXT_RE = re.compile(
    r"(?:deadline|due\s+(?:date|by)|close\s+(?:date|by)|application\s+(?:close|due|deadline)|"
    r"submit(?:tal)?(?:\s+by)?|must\s+(?:be\s+)?(?:received|submitted)|"
    r"no\s+later\s+than|by\s+(?:end\s+of\s+)?(?:business\s+)?(?:day\s+)?)",
    re.I,
)

_MONTH_MAP = {name: i + 1 for i, name in enumerate(_MONTH_NAMES)}
_MONTH_MAP.update({name: i + 1 for i, name in enumerate(_MONTH_ABBR)})


def _parse_month(m: str) -> int:
    return _MONTH_MAP[m.lower().rstrip(".")]


def _to_datetime(year: int, month: int, day: int) -> datetime | None:
    try:
        return datetime(year, month, day, 23, 59, 59)
    except ValueError:
        return None


def extract_deadline(html: bytes, text: str) -> datetime | None:
    """Return the application deadline as UTC-naive datetime, or None.

    Searches for deadline-context cues within 200 chars before each date pattern.
    Returns the earliest future-looking date found (most conservative).
    If multiple deadlines found without context, returns None (ambiguous).
    """
    try:
        candidates: list[datetime] = []
        _collect_deadline_dates(text, candidates)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        # Multiple candidates — return earliest (soonest deadline is conservative)
        return min(candidates)
    except Exception:
        logger.debug("extract_deadline failed", exc_info=True)
        return None


def _collect_deadline_dates(text: str, out: list[datetime]) -> None:
    """Find dates preceded by deadline-context cues within 200 chars."""
    seen: set[tuple] = set()

    def _add(year: int, month: int, day: int) -> None:
        key = (year, month, day)
        if key not in seen:
            seen.add(key)
            dt = _to_datetime(year, month, day)
            if dt:
                out.append(dt)

    # Scan long month name dates
    for m in _DATE_LONG_RE.finditer(text):
        start = max(0, m.start() - 200)
        snippet = text[start : m.start()]
        if not _DEADLINE_CONTEXT_RE.search(snippet):
            continue
        try:
            month_str = m.group(0).split()[0]
            day = int(m.group(1))
            year = int(m.group(2))
            _add(year, _parse_month(month_str), day)
        except (ValueError, IndexError):
            continue

    # Abbreviated month dates
    for m in _DATE_ABBR_RE.finditer(text):
        start = max(0, m.start() - 200)
        snippet = text[start : m.start()]
        if not _DEADLINE_CONTEXT_RE.search(snippet):
            continue
        try:
            month_str = m.group(0).split()[0]
            day = int(m.group(1))
            year = int(m.group(2))
            _add(year, _parse_month(month_str), day)
        except (ValueError, IndexError):
            continue

    # Slash dates (MM/DD/YYYY)
    for m in _DATE_SLASH_RE.finditer(text):
        start = max(0, m.start() - 200)
        snippet = text[start : m.start()]
        if not _DEADLINE_CONTEXT_RE.search(snippet):
            continue
        try:
            month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                _add(year, month, day)
        except (ValueError, IndexError):
            continue


# ---------------------------------------------------------------------------
# Award range extraction
# ---------------------------------------------------------------------------


def _parse_dollar(amount_str: str, multiplier_str: str) -> Decimal | None:
    """Parse "$1,234" or "1234" plus optional "K"/"M" multiplier to Decimal."""
    try:
        val = Decimal(amount_str.replace(",", ""))
        mult = multiplier_str.lower() if multiplier_str else ""
        if mult in ("k", "thousand"):
            val *= 1000
        elif mult in ("m", "million"):
            val *= 1_000_000
        return val
    except InvalidOperation:
        return None


# "$X[K|M] to/- $Y[K|M]" range pattern
_RANGE_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(K|M|thousand|million)?"
    r"\s*(?:to|–|-|through)\s*"
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(K|M|thousand|million)?",
    re.I,
)

# "up to / maximum of / not to exceed $X[K|M]"
_MAX_RE = re.compile(
    r"(?:up to|maximum(?:\s+(?:award\s+(?:amount\s+)?(?:of\s+)?|of\s+)?)?|not to exceed|awards?\s+(?:up\s+to|not\s+(?:to\s+)?exceed))\s*"
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(K|M|thousand|million)?",
    re.I,
)

# Words that signal "total pool" context rather than individual award ceiling.
_TOTAL_POOL_CONTEXT_RE = re.compile(r"\b(?:total|in all|program|pool|combined|aggregate)\b", re.I)

# "minimum / at least / starting at / as low as $X[K|M]"
_MIN_RE = re.compile(
    r"(?:minimum(?:\s+(?:award\s+(?:amount\s+)?(?:of\s+)?|of\s+)?)?|at least|starting at|as low as|from)\s*"
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(K|M|thousand|million)?",
    re.I,
)


def extract_award_range(html: bytes, text: str) -> tuple[Decimal | None, Decimal | None]:
    """Return (award_min, award_max) as Decimal or None for each unextracted bound.

    Tries range pattern first, then individual max/min patterns.
    Returns (None, None) if nothing confidently extractable.
    """
    try:
        return _do_extract_award_range(text)
    except Exception:
        logger.debug("extract_award_range failed", exc_info=True)
        return None, None


def _do_extract_award_range(text: str) -> tuple[Decimal | None, Decimal | None]:
    # Range pattern takes priority
    m = _RANGE_RE.search(text)
    if m:
        lo = _parse_dollar(m.group(1), m.group(2) or "")
        hi = _parse_dollar(m.group(3), m.group(4) or "")
        if lo is not None and hi is not None and lo <= hi:
            return lo, hi

    award_max: Decimal | None = None
    award_min: Decimal | None = None

    m = _MAX_RE.search(text)
    if m:
        prefix = text[max(0, m.start() - 80) : m.start()]
        if not _TOTAL_POOL_CONTEXT_RE.search(prefix):
            award_max = _parse_dollar(m.group(1), m.group(2) or "")

    m = _MIN_RE.search(text)
    if m:
        award_min = _parse_dollar(m.group(1), m.group(2) or "")

    return award_min, award_max


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------


def extract_status(close_at: datetime | None, now: datetime) -> str:
    """Return 'open' or 'closed' based on close_at vs now.

    Rolling opportunities (close_at=None) are treated as open.
    """
    if close_at is None:
        return "open"
    return "open" if close_at > now else "closed"


# ---------------------------------------------------------------------------
# Org type extraction
# ---------------------------------------------------------------------------

_ORG_TYPE_501C3_RE = re.compile(
    r"501\s*\(c\)\s*\(?3\)?|501c3|tax.exempt\s+(?:nonprofit|organization)|"
    r"IRS-?recognized\s+(?:tax.exempt|nonprofit)",
    re.I,
)
_ORG_TYPE_NONPROFIT_RE = re.compile(
    r"\bnonprofit\s+(?:organizations?|entities|entity|corp(?:oration)?s?|applicants?)\b|"
    r"\bnon-profit\s+(?:organizations?|entities|entity|corp(?:oration)?s?|applicants?)\b",
    re.I,
)


def extract_org_type(html: bytes, text: str) -> str | None:
    """Return '501c3', 'nonprofit_general', or None.

    Returns '501c3' if 501(c)(3) is explicitly mentioned in an eligibility context.
    Returns 'nonprofit_general' if generic nonprofit language is present.
    Returns None if neither is clearly stated.
    """
    try:
        if _ORG_TYPE_501C3_RE.search(text):
            return "501c3"
        if _ORG_TYPE_NONPROFIT_RE.search(text):
            return "nonprofit_general"
        return None
    except Exception:
        logger.debug("extract_org_type failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# DC agency extraction from page body
# ---------------------------------------------------------------------------


def extract_dc_agency(text: str) -> str | None:
    """Return canonical DC agency name by searching full page body text.

    Searches for both abbreviations (OSSE, DOES) and full names
    (Office of the State Superintendent of Education). Returns the
    first match, preferring longer/more-specific matches via regex ordering.
    Returns None if no recognized agency is found.
    """
    try:
        m = _AGENCY_BODY_RE.search(text)
        if not m:
            return None
        matched_key = m.group(1)
        # Case-insensitive lookup: find the canonical key
        matched_lower = matched_key.lower()
        for key, canonical in DC_AGENCY_TAXONOMY.items():
            if key.lower() == matched_lower:
                return canonical
        return None
    except Exception:
        logger.debug("extract_dc_agency failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Title keyword augmentation
# ---------------------------------------------------------------------------


def augment_subject_areas_from_title(title: str, base_areas: list[str]) -> list[str]:
    """Add subject_area codes to base_areas based on keyword matches in title.

    Returns a new list with duplicates removed, preserving insertion order.
    Never modifies base_areas in place.
    """
    try:
        result = list(base_areas)
        seen = set(result)
        for pattern, code in _TITLE_KEYWORD_MAP:
            if code not in seen and pattern.search(title):
                result.append(code)
                seen.add(code)
        return result
    except Exception:
        logger.debug("augment_subject_areas_from_title failed", exc_info=True)
        return list(base_areas)


# ---------------------------------------------------------------------------
# Budget cap extraction (for HumanitiesDC "under $2M budget" eligibility)
# ---------------------------------------------------------------------------

_BUDGET_CAP_RE = re.compile(
    r"(?:budgets?|annual\s+budgets?|operating\s+budgets?)\s*(?:of\s+)?(?:under|below|less\s+than|not\s+(?:to\s+)?exceed(?:ing)?)\s*"
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(K|M|thousand|million)?",
    re.I,
)
_BUDGET_CAP_ALT_RE = re.compile(
    r"(?:under|below|less\s+than)\s*\$\s*([\d,]+(?:\.\d+)?)\s*(K|M|thousand|million)?\s*"
    r"(?:annual\s+)?(?:operating\s+)?budgets?",
    re.I,
)


def extract_budget_cap(text: str) -> Decimal | None:
    """Return maximum budget eligibility cap (e.g. $2,000,000), or None.

    Looks for patterns like 'budget under $2M', 'annual budget below $2,000,000'.
    """
    try:
        for pattern in (_BUDGET_CAP_RE, _BUDGET_CAP_ALT_RE):
            m = pattern.search(text)
            if m:
                val = _parse_dollar(m.group(1), m.group(2) or "")
                if val is not None and val > 0:
                    return val
        return None
    except Exception:
        logger.debug("extract_budget_cap failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# HTML -> plain text (strip tags, collapse whitespace)
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>", re.S)
_WHITESPACE_RE = re.compile(r"\s+")


def html_to_text(html: bytes) -> str:
    """Strip HTML tags and collapse whitespace to produce plain text for extraction."""
    try:
        raw = html.decode("utf-8", errors="ignore")
        stripped = _TAG_RE.sub(" ", raw)
        return _WHITESPACE_RE.sub(" ", stripped).strip()
    except Exception:
        return ""
