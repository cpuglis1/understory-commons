"""RawRecord model — one row per unique fetched document (keyed by content_sha)."""

from django.db import models


class RawRecord(models.Model):
    """Immutable record of a fetched document. content_sha is the primary key.

    Append-only: save() raises if the row already exists. Corrections are
    not possible; a re-fetch with new content produces a new sha and a new row.
    """

    content_sha = models.CharField(max_length=64, primary_key=True)
    fetch_url = models.URLField(max_length=2048)
    fetched_at = models.DateTimeField(db_index=True)
    source_id = models.CharField(max_length=64, db_index=True)
    mime_type = models.CharField(max_length=128)
    content_ref = models.CharField(max_length=512)  # object store URI
    http_status = models.IntegerField()
    fetch_metadata = models.JSONField(default=dict)

    class Meta:
        app_label = "grants_ingest"

    def __str__(self) -> str:
        return f"{self.source_id}:{self.content_sha[:12]}"

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValueError("RawRecord is append-only and cannot be updated.")
        super().save(*args, **kwargs)
