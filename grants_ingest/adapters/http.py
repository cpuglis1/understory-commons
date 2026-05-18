"""HTTP utilities: rate-limiting, retry, robots.txt compliance.

Used by BaseAdapter._http_get. All adapters share these; source-specific
logic lives only in iter_fetch_tasks() and parse().
"""

import hashlib
import logging
import time
import urllib.robotparser
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def _get_robots(host: str, client: httpx.Client) -> urllib.robotparser.RobotFileParser:
    if host in _robots_cache:
        return _robots_cache[host]
    rp = urllib.robotparser.RobotFileParser()
    robots_url = f"https://{host}/robots.txt"
    try:
        resp = client.get(robots_url, timeout=10)
        rp.parse(resp.text.splitlines())
    except Exception:
        pass
    _robots_cache[host] = rp
    return rp


def http_get(
    url: str,
    client: httpx.Client,
    rate_limit_per_sec: float = 1.0,
    robots_compliance: str = "strict",
    _last_request_time: dict | None = None,
    _sleep_fn=time.sleep,
) -> httpx.Response:
    """Fetch url with rate-limiting, robots.txt compliance, and retry.

    Rate limit: enforces minimum gap between consecutive calls using
    _last_request_time dict (mutable, shared by callers for per-host tracking).

    Retry: up to 3 attempts on 5xx or connection errors; exponential backoff
    with jitter (1s, 2s, 4s caps). Raises on 4xx (except 429 which retries).

    Robots: on 'strict', checks robots.txt and raises RobotsBlocked if disallowed.
    """
    parsed = urlparse(url)
    host = parsed.netloc

    if robots_compliance == "strict":
        rp = _get_robots(host, client)
        if not rp.can_fetch("*", url):
            raise RobotsBlocked(url)

    if _last_request_time is None:
        _last_request_time = {}

    min_gap = 1.0 / rate_limit_per_sec
    last = _last_request_time.get(host, 0.0)
    elapsed = time.monotonic() - last
    if elapsed < min_gap:
        _sleep_fn(min_gap - elapsed)

    max_attempts = 3
    for attempt in range(max_attempts):
        _last_request_time[host] = time.monotonic()
        try:
            resp = client.get(url, timeout=30)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            if attempt == max_attempts - 1:
                raise
            backoff = (2**attempt) + 0.1 * attempt
            logger.warning("Connection error on %s (attempt %d): %s", url, attempt + 1, exc)
            _sleep_fn(backoff)
            continue

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
            logger.warning("Rate limited on %s, sleeping %ss", url, retry_after)
            _sleep_fn(retry_after)
            continue

        if 500 <= resp.status_code < 600:
            if attempt == max_attempts - 1:
                resp.raise_for_status()
            backoff = (2**attempt) + 0.1 * attempt
            logger.warning("5xx on %s (attempt %d): %d", url, attempt + 1, resp.status_code)
            _sleep_fn(backoff)
            continue

        return resp

    raise RuntimeError(f"http_get exhausted retries for {url}")


def compute_sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class RobotsBlocked(Exception):
    """Raised when robots.txt disallows the requested URL."""
