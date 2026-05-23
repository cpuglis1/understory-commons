"""Tests for dc_html_util shared utilities."""

import re

from grants_ingest.adapters.dc_html_util import (
    DC_AGENCY_NAMES,
    extract_moca_agency,
    extract_title,
    scan_hrefs,
)


def test_extract_title_basic():
    body = b"<html><head><title>My Grant Program | dcarts</title></head></html>"
    assert extract_title(body) == "My Grant Program"


def test_extract_title_no_separator():
    body = b"<html><head><title>Plain Title</title></head></html>"
    assert extract_title(body) == "Plain Title"


def test_extract_title_empty():
    assert extract_title(b"<html><body>no title</body></html>") == ""


def test_extract_title_html_entities():
    body = (
        b"<html><head><title>FY27 Pre-K &amp; Literacy | Mayor&#39;s Office</title></head></html>"
    )
    assert extract_title(body) == "FY27 Pre-K & Literacy"


def test_extract_title_multiline_tag():
    body = b"<html><head><title\n>Grants | learn24</title></head></html>"
    assert extract_title(body) == "Grants"


def test_scan_hrefs_finds_matches():
    body = b'<a href="/publication/fy27-osse-nofa">link</a><a href="/other">skip</a>'
    pattern = re.compile(r'href=["\'](/publication/[^"\']+)["\']', re.I)
    result = scan_hrefs(body, pattern)
    assert result == ["/publication/fy27-osse-nofa"]


def test_scan_hrefs_empty():
    body = b"<p>no links here</p>"
    pattern = re.compile(r'href=["\'](/publication/[^"\']+)["\']', re.I)
    assert scan_hrefs(body, pattern) == []


def test_extract_moca_agency_osse():
    assert extract_moca_agency("OSSE FY27 Pre-K Enhancement NOFA") == DC_AGENCY_NAMES["OSSE"]


def test_extract_moca_agency_does():
    assert extract_moca_agency("FY27 DOES Youth Workforce Program NOFA") == DC_AGENCY_NAMES["DOES"]


def test_extract_moca_agency_dhcd():
    assert extract_moca_agency("DHCD Community Development Initiative") == DC_AGENCY_NAMES["DHCD"]


def test_extract_moca_agency_unrecognized():
    assert extract_moca_agency("FY27 Community Safety Initiative NOFA") is None


def test_extract_moca_agency_dc_health():
    assert extract_moca_agency("DC Health FY27 HIV Prevention NOFA") == DC_AGENCY_NAMES["DC Health"]
