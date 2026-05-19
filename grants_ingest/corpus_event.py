"""CorpusEvent — append-only event log for the ingestion pipeline.

Lives in the main app DB (default alias). Every fetch, parse, upsert,
resolution, and status change produces an event row. The event log is the
source of truth; registry tables (Funder, HistoricalGrant, etc.) are
materialized views that can be rebuilt by replaying events from zero.

opportunity_id, funder_id, program_id are plain UUIDFields rather than
ForeignKeys because events are logged before the materializer creates the
corresponding registry rows, and referenced rows may legitimately not exist
at write time.
"""

from django.db import models


class CorpusEventType(models.TextChoices):
    SEEN = "seen", "Seen"
    FUNDER_UPSERTED = "funder_upserted", "Funder upserted"
    FUNDER_ENRICHED = "funder_enriched", "Funder enriched"
    HISTORICAL_GRANT_RECORDED = "historical_grant_recorded", "Historical grant recorded"
    RESOLVED = "resolved", "Resolved"
    MERGED = "merged", "Merged"
    SPLIT = "split", "Split"
    STATUS_CHANGED = "status_changed", "Status changed"
    WITHDRAWN = "withdrawn", "Withdrawn"
    PARSE_FAILED = "parse_failed", "Parse failed"
    ROBOTS_BLOCKED = "robots_blocked", "Robots blocked"
    OPPORTUNITY_SEEN = "opportunity_seen", "Opportunity seen"
    OPPORTUNITY_UPDATED = "opportunity_updated", "Opportunity updated"
    OPPORTUNITY_FILTERED = "opportunity_filtered", "Opportunity filtered"


class CorpusEvent(models.Model):
    """Append-only event log entry."""

    id = models.BigAutoField(primary_key=True)
    timestamp = models.DateTimeField(db_index=True)
    event_type = models.CharField(max_length=32, choices=CorpusEventType.choices)
    source_id = models.CharField(max_length=64, db_index=True)
    content_sha = models.CharField(max_length=64, blank=True, default="", db_index=True)
    opportunity_id = models.UUIDField(null=True, blank=True, db_index=True)
    funder_id = models.UUIDField(null=True, blank=True, db_index=True)
    program_id = models.UUIDField(null=True, blank=True, db_index=True)
    payload = models.JSONField(default=dict)
    actor = models.CharField(max_length=128)  # e.g. 'system:propublica_np_v0.1.0'

    class Meta:
        app_label = "grants_ingest"
        indexes = [
            models.Index(fields=["source_id", "timestamp"]),
            models.Index(fields=["opportunity_id", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}:{self.source_id}@{self.timestamp}"

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValueError("CorpusEvent is append-only and cannot be updated.")
        super().save(*args, **kwargs)
