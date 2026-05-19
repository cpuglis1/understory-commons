"""BaseAdapter — shared fetch loop, idempotent store, event logging."""

import logging
from collections.abc import Iterable
from typing import ClassVar

import httpx
from django.utils import timezone

from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.raw_record import RawRecord
from grants_ingest.storage.base import RawObjectStore

from .event_log import EventLogWriter
from .http import RobotsBlocked, compute_sha, http_get
from .types import AdapterRunResult, FetchTask

logger = logging.getLogger(__name__)


class BaseAdapter:
    source_id: ClassVar[str]
    version: ClassVar[str]
    rate_limit_per_sec: ClassVar[float] = 1.0
    robots_compliance: ClassVar[str] = "strict"

    def __init__(self, store: RawObjectStore, event_log: EventLogWriter) -> None:
        self.store = store
        self.event_log = event_log
        self._last_request_time: dict = {}

    def iter_fetch_tasks(self, **kwargs) -> Iterable[FetchTask]:
        raise NotImplementedError

    def fetch_one(self, task: FetchTask, client: httpx.Client) -> tuple[RawRecord, bool]:
        """Fetch url, content-address the body, idempotent-write to store.

        Always logs a 'seen' event regardless of whether the body is new.
        Returns (raw_record, is_new) where is_new is True only for first-ever store.
        """
        try:
            resp = http_get(
                task.url,
                client,
                rate_limit_per_sec=self.rate_limit_per_sec,
                robots_compliance=self.robots_compliance,
                _last_request_time=self._last_request_time,
            )
        except RobotsBlocked:
            self.event_log.append(
                CorpusEventType.ROBOTS_BLOCKED,
                payload={"url": task.url},
            )
            raise

        body = resp.content
        sha = compute_sha(body)
        fetched_at = timezone.now()

        sidecar = {
            "source_id": self.source_id,
            "fetch_url": task.url,
            "fetched_at": fetched_at.isoformat(),
            "mime_type": resp.headers.get("content-type", task.expected_mime),
            "http_status": resp.status_code,
            "headers": dict(resp.headers),
            **task.extra_metadata,
        }

        content_ref = self.store.put(sha, body, sidecar)
        is_new = not RawRecord.objects.filter(content_sha=sha).exists()

        if is_new:
            raw = RawRecord.objects.create(
                content_sha=sha,
                fetch_url=task.url,
                fetched_at=fetched_at,
                source_id=self.source_id,
                mime_type=sidecar["mime_type"],
                content_ref=content_ref,
                http_status=resp.status_code,
                fetch_metadata=task.extra_metadata,
            )
        else:
            raw = RawRecord.objects.get(content_sha=sha)

        self.event_log.append(
            CorpusEventType.SEEN,
            content_sha=sha,
            payload={"url": task.url, "http_status": resp.status_code, "is_new": is_new},
        )
        return raw, is_new

    def parse(self, raw: RawRecord) -> list:
        """Tier A: return a list of (event_type, payload) pairs to log.
        Tier B/C: return []. Overridden by concrete adapters.
        """
        return []

    def run(self, **kwargs) -> AdapterRunResult:
        result = AdapterRunResult(source_id=self.source_id)
        with httpx.Client(follow_redirects=True) as client:
            for task in self.iter_fetch_tasks(**kwargs):
                try:
                    raw, is_new = self.fetch_one(task, client)
                except RobotsBlocked:
                    result.robots_blocked += 1
                    continue
                except Exception as exc:
                    logger.error("Error fetching %s: %s", task.url, exc)
                    result.errors.append(str(exc))
                    continue

                result.fetched += 1
                if is_new:
                    result.stored_new += 1

                try:
                    events = self.parse(raw)
                    for event_type, payload in events:
                        self.event_log.append(
                            event_type, payload=payload, content_sha=raw.content_sha
                        )
                except Exception as exc:
                    logger.error("Error parsing %s: %s", task.url, exc)
                    result.parse_errors += 1
                    result.errors.append(str(exc))
        return result
