"""Thin writer for appending CorpusEvent rows from adapter code."""

from django.utils import timezone

from grants_ingest.corpus_event import CorpusEvent, CorpusEventType


class EventLogWriter:
    def __init__(self, source_id: str, actor: str) -> None:
        self.source_id = source_id
        self.actor = actor

    def append(
        self,
        event_type: CorpusEventType | str,
        *,
        content_sha: str = "",
        funder_id=None,
        program_id=None,
        opportunity_id=None,
        payload: dict | None = None,
    ) -> CorpusEvent:
        return CorpusEvent.objects.create(
            timestamp=timezone.now(),
            event_type=event_type,
            source_id=self.source_id,
            content_sha=content_sha,
            funder_id=funder_id,
            program_id=program_id,
            opportunity_id=opportunity_id,
            payload=payload or {},
            actor=self.actor,
        )
