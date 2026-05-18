"""Tests for BaseAdapter HTTP utilities: rate-limit, retry, fetch_one idempotency.

Uses httpx.MockTransport — no live network calls.
"""

import hashlib

import httpx
import pytest

from grants_ingest.adapters.http import compute_sha, http_get
from grants_ingest.adapters.types import FetchTask

# ---------------------------------------------------------------------------
# http_get helpers
# ---------------------------------------------------------------------------


def _mock_client(responses: list[httpx.Response]) -> httpx.Client:
    """Build a client whose transport returns responses in sequence."""
    call_count = {"n": 0}

    def handler(request):
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return responses[idx]

    return httpx.Client(transport=httpx.MockTransport(handler))


def _resp(status: int, body: bytes = b"ok") -> httpx.Response:
    return httpx.Response(status, content=body)


# ---------------------------------------------------------------------------
# Rate-limit test
# ---------------------------------------------------------------------------


def test_rate_limit_honoured():
    """Two requests to the same host must be spaced by 1/rate_limit_per_sec."""
    sleep_calls = []

    def fake_sleep(s):
        sleep_calls.append(s)

    client = _mock_client([_resp(200), _resp(200)])
    last = {}
    http_get(
        "https://example.com/a",
        client,
        rate_limit_per_sec=1.0,
        robots_compliance="none",
        _last_request_time=last,
        _sleep_fn=fake_sleep,
    )
    # Simulate almost no time has passed
    last["example.com"] = last["example.com"] - 0.1
    http_get(
        "https://example.com/b",
        client,
        rate_limit_per_sec=1.0,
        robots_compliance="none",
        _last_request_time=last,
        _sleep_fn=fake_sleep,
    )

    assert len(sleep_calls) >= 1
    assert sleep_calls[0] > 0.5


# ---------------------------------------------------------------------------
# Retry on 5xx
# ---------------------------------------------------------------------------


def test_retry_on_5xx():
    """Should retry up to 3 times on 5xx; succeed on the 3rd attempt."""
    sleep_calls = []
    client = _mock_client([_resp(503), _resp(503), _resp(200, b"success")])
    resp = http_get(
        "https://example.com/retry",
        client,
        robots_compliance="none",
        _last_request_time={},
        _sleep_fn=lambda s: sleep_calls.append(s),
    )
    assert resp.status_code == 200
    assert len(sleep_calls) == 2  # slept before attempt 2 and 3


def test_raises_after_max_retries_5xx():
    """Three 5xx in a row should raise."""
    client = _mock_client([_resp(500), _resp(500), _resp(500)])
    with pytest.raises(httpx.HTTPStatusError):
        http_get(
            "https://example.com/fail",
            client,
            robots_compliance="none",
            _last_request_time={},
            _sleep_fn=lambda s: None,
        )


# ---------------------------------------------------------------------------
# Abort on 4xx (non-429)
# ---------------------------------------------------------------------------


def test_no_retry_on_404():
    """4xx (not 429) should be returned immediately without retry."""
    sleep_calls = []
    client = _mock_client([_resp(404)])
    resp = http_get(
        "https://example.com/notfound",
        client,
        robots_compliance="none",
        _last_request_time={},
        _sleep_fn=lambda s: sleep_calls.append(s),
    )
    assert resp.status_code == 404
    assert sleep_calls == []


# ---------------------------------------------------------------------------
# Sha computation
# ---------------------------------------------------------------------------


def test_compute_sha_matches_hashlib():
    body = b"grant corpus test content"
    assert compute_sha(body) == hashlib.sha256(body).hexdigest()


# ---------------------------------------------------------------------------
# fetch_one idempotency (requires DB)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_fetch_one_idempotency(tmp_path):
    """Two fetch_one calls with the same body produce one stored object and two seen events."""
    from grants_ingest.adapters.base import BaseAdapter
    from grants_ingest.adapters.event_log import EventLogWriter
    from grants_ingest.corpus_event import CorpusEventType
    from grants_ingest.models import CorpusEvent, RawRecord
    from grants_ingest.storage.fs import FileSystemRawObjectStore

    store = FileSystemRawObjectStore(root=tmp_path)
    log = EventLogWriter(source_id="test_source", actor="system:test")

    class ConcreteAdapter(BaseAdapter):
        source_id = "test_source"
        version = "0.1.0"

        def iter_fetch_tasks(self, **kwargs):
            return []

    adapter = ConcreteAdapter(store=store, event_log=log)
    task = FetchTask(url="https://example.com/doc", expected_mime="application/json")

    body = b'{"name": "Synthetic Foundation"}'

    def handler(request):
        return httpx.Response(200, content=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    # First fetch
    raw1 = adapter.fetch_one(task, client)
    # Second fetch — same bytes
    raw2 = adapter.fetch_one(task, client)

    assert raw1.content_sha == raw2.content_sha
    assert RawRecord.objects.filter(content_sha=raw1.content_sha).count() == 1
    seen_events = CorpusEvent.objects.filter(event_type=CorpusEventType.SEEN)
    assert seen_events.count() == 2
