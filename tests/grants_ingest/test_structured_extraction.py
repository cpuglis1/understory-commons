"""Tests for grants_ingest/extraction/structured.py deterministic extractors."""

from datetime import datetime
from decimal import Decimal

from grants_ingest.extraction.structured import (
    augment_subject_areas_from_title,
    extract_award_range,
    extract_budget_cap,
    extract_dc_agency,
    extract_deadline,
    extract_org_type,
    extract_status,
    html_to_text,
)

# ---------------------------------------------------------------------------
# extract_deadline
# ---------------------------------------------------------------------------


class TestExtractDeadline:
    def _call(self, text: str) -> datetime | None:
        return extract_deadline(b"", text)

    def test_long_month_with_deadline_cue(self):
        text = "Application Deadline: March 15, 2026"
        result = self._call(text)
        assert result == datetime(2026, 3, 15, 23, 59, 59)

    def test_slash_date_with_due_cue(self):
        text = "Applications due by 06/30/2026."
        result = self._call(text)
        assert result == datetime(2026, 6, 30, 23, 59, 59)

    def test_abbreviated_month(self):
        text = "Submit by: Apr. 1, 2026"
        result = self._call(text)
        assert result == datetime(2026, 4, 1, 23, 59, 59)

    def test_no_deadline_cue_returns_none(self):
        text = "The program began in January 2025 and runs through June 2026."
        result = self._call(text)
        assert result is None

    def test_empty_text_returns_none(self):
        assert self._call("") is None

    def test_multiple_deadlines_returns_earliest(self):
        text = (
            "The application deadline is April 30, 2026. "
            "Note the close date of May 15, 2026 for late submissions."
        )
        result = self._call(text)
        assert result == datetime(2026, 4, 30, 23, 59, 59)

    def test_no_crash_on_garbage_input(self):
        result = self._call("$$$ @@@  ??? ---")
        assert result is None


# ---------------------------------------------------------------------------
# extract_award_range
# ---------------------------------------------------------------------------


class TestExtractAwardRange:
    def _call(self, text: str) -> tuple:
        return extract_award_range(b"", text)

    def test_explicit_range_dollar(self):
        text = "Awards range from $10,000 to $50,000."
        lo, hi = self._call(text)
        assert lo == Decimal("10000")
        assert hi == Decimal("50000")

    def test_range_with_k_suffix(self):
        text = "Grants from $25K to $150K are available."
        lo, hi = self._call(text)
        assert lo == Decimal("25000")
        assert hi == Decimal("150000")

    def test_max_only_up_to(self):
        text = "Awards up to $100,000."
        lo, hi = self._call(text)
        assert lo is None
        assert hi == Decimal("100000")

    def test_max_only_not_to_exceed(self):
        text = "Maximum award: not to exceed $75,000."
        lo, hi = self._call(text)
        assert hi == Decimal("75000")

    def test_max_with_million(self):
        text = "Awards up to $1,000,000 per organization are available."
        lo, hi = self._call(text)
        assert hi == Decimal("1000000")

    def test_no_dollar_amounts(self):
        lo, hi = self._call("No funding information available.")
        assert lo is None
        assert hi is None

    def test_no_crash_on_empty(self):
        lo, hi = self._call("")
        assert lo is None and hi is None

    def test_inverted_range_ignored(self):
        # $100 to $50 is semantically invalid — should not produce a range
        text = "$100,000 to $50,000 available"
        lo, hi = self._call(text)
        # range regex would catch it but lo > hi check rejects; falls through
        # to individual max/min scan which may or may not pick something up
        # The key assertion: lo is never greater than hi from the range path
        if lo is not None and hi is not None:
            assert lo <= hi

    def test_total_pool_context_excluded(self):
        # "In total, up to $22.1 million" is program-level funding, not award ceiling
        text = "In total, up to $22.1 million will be awarded across all programs."
        lo, hi = self._call(text)
        assert hi is None


# ---------------------------------------------------------------------------
# extract_status
# ---------------------------------------------------------------------------


class TestExtractStatus:
    _now = datetime(2026, 5, 23, 12, 0, 0)

    def test_future_deadline_is_open(self):
        assert extract_status(datetime(2026, 12, 31), self._now) == "open"

    def test_past_deadline_is_closed(self):
        assert extract_status(datetime(2025, 1, 1), self._now) == "closed"

    def test_none_deadline_is_open(self):
        assert extract_status(None, self._now) == "open"


# ---------------------------------------------------------------------------
# extract_org_type
# ---------------------------------------------------------------------------


class TestExtractOrgType:
    def _call(self, text: str) -> str | None:
        return extract_org_type(b"", text)

    def test_501c3_explicit(self):
        text = "Eligible applicants must be 501(c)(3) organizations."
        assert self._call(text) == "501c3"

    def test_501c3_no_parens(self):
        assert self._call("Must be a 501c3 nonprofit.") == "501c3"

    def test_nonprofit_general(self):
        text = "Open to nonprofit organizations based in the DMV."
        assert self._call(text) == "nonprofit_general"

    def test_no_org_type_language(self):
        text = "Contact the grants office for eligibility questions."
        assert self._call(text) is None

    def test_501c3_takes_precedence_over_nonprofit(self):
        text = "Nonprofit organizations that are 501(c)(3) tax-exempt are eligible."
        assert self._call(text) == "501c3"

    def test_no_crash_on_empty(self):
        assert self._call("") is None


# ---------------------------------------------------------------------------
# extract_dc_agency
# ---------------------------------------------------------------------------


class TestExtractDCAgency:
    def test_abbreviation_osse(self):
        text = "This grant is issued by OSSE for early childhood programs."
        assert extract_dc_agency(text) == "DC Office of the State Superintendent of Education"

    def test_abbreviation_does(self):
        text = "DOES Youth Workforce NOFA FY27"
        assert extract_dc_agency(text) == "DC Department of Employment Services"

    def test_full_name_match(self):
        text = "Department of Behavioral Health invites proposals."
        assert extract_dc_agency(text) == "DC Department of Behavioral Health"

    def test_no_match_returns_none(self):
        text = "Community initiative supporting local nonprofits."
        assert extract_dc_agency(text) is None

    def test_dc_health_abbreviation(self):
        text = "DC Health FY27 HIV Prevention funding opportunity."
        assert extract_dc_agency(text) == "DC Department of Health"

    def test_no_crash_on_empty(self):
        assert extract_dc_agency("") is None


# ---------------------------------------------------------------------------
# augment_subject_areas_from_title
# ---------------------------------------------------------------------------


class TestAugmentSubjectAreas:
    def test_stem_keyword(self):
        result = augment_subject_areas_from_title("FY27 STEM Education Grant", ["education"])
        assert "stem" in result
        assert "education" in result

    def test_literacy_keyword(self):
        result = augment_subject_areas_from_title("Youth Literacy Program", [])
        assert "literacy" in result

    def test_no_keyword_match(self):
        result = augment_subject_areas_from_title("General Community Grant", ["general"])
        assert result == ["general"]

    def test_no_duplicates(self):
        result = augment_subject_areas_from_title("Arts Program", ["arts", "youth_development"])
        assert result.count("arts") == 1

    def test_base_areas_not_mutated(self):
        base = ["humanities"]
        augment_subject_areas_from_title("Dance and Theater Grant", base)
        assert base == ["humanities"]

    def test_empty_title(self):
        result = augment_subject_areas_from_title("", ["general"])
        assert result == ["general"]


# ---------------------------------------------------------------------------
# extract_budget_cap
# ---------------------------------------------------------------------------


class TestExtractBudgetCap:
    def test_under_two_million(self):
        text = "Applicants must have an annual budget under $2M."
        assert extract_budget_cap(text) == Decimal("2000000")

    def test_less_than_with_commas(self):
        text = "Organizations with operating budgets less than $500,000 are eligible."
        assert extract_budget_cap(text) == Decimal("500000")

    def test_no_budget_language(self):
        assert extract_budget_cap("No budget restrictions apply.") is None

    def test_no_crash_on_empty(self):
        assert extract_budget_cap("") is None


# ---------------------------------------------------------------------------
# html_to_text
# ---------------------------------------------------------------------------


class TestHtmlToText:
    def test_strips_tags(self):
        html = b"<p><strong>Deadline:</strong> March 15, 2026</p>"
        text = html_to_text(html)
        assert "<" not in text
        assert "Deadline:" in text
        assert "March 15, 2026" in text

    def test_collapses_whitespace(self):
        html = b"<p>hello   \n\n  world</p>"
        text = html_to_text(html)
        assert "  " not in text

    def test_empty_bytes(self):
        assert html_to_text(b"") == ""
