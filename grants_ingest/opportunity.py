"""OpportunityInstance, CorpusSnapshot, and IngestHealthSnapshot models.

No OpportunityInstance rows are produced in slice 1 (irs_990pf + propublica_np
produce funder-level data and historical grants, not opportunity instances).
Models ship now so the schema is stable and later slices don't churn migrations.
"""

import uuid

from django.db import models

from .registry import Funder, OpportunityStatus, Program, ProgramType


class OpportunityInstance(models.Model):
    """A specific grant cycle / application window from a funder program."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(
        Program, on_delete=models.PROTECT, null=True, blank=True, related_name="instances"
    )
    funder = models.ForeignKey(
        Funder, on_delete=models.PROTECT, null=True, blank=True, related_name="instances"
    )
    title = models.CharField(max_length=512)
    application_open_at = models.DateTimeField(null=True, blank=True)
    application_close_at = models.DateTimeField(null=True, blank=True)
    rolling = models.BooleanField(default=False)
    award_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    award_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    typical_award = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total_pool = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    program_type = models.CharField(
        max_length=32, choices=ProgramType.choices, default=ProgramType.UNKNOWN
    )
    eligibility = models.JSONField(default=dict)
    geographic_scope = models.JSONField(default=dict)
    subject_areas = models.JSONField(default=list)
    status = models.CharField(
        max_length=32, choices=OpportunityStatus.choices, default=OpportunityStatus.OPEN
    )
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    extraction_model_version = models.CharField(max_length=64, blank=True, default="")
    schema_version = models.CharField(max_length=32, blank=True, default="")
    provenance = models.JSONField(default=dict)
    source_records = models.ManyToManyField(
        "grants_ingest.RawRecord", related_name="opportunities", blank=True
    )

    class Meta:
        app_label = "grants_ingest"

    def __str__(self) -> str:
        return self.title


class CorpusSnapshot(models.Model):
    """Point-in-time tag for reproducible training and evaluation runs."""

    tag = models.CharField(max_length=128, primary_key=True)
    event_log_position = models.BigIntegerField()
    object_store_manifest_ref = models.CharField(max_length=64)
    created_at = models.DateTimeField()
    notes = models.TextField(blank=True, default="")

    class Meta:
        app_label = "grants_ingest"

    def __str__(self) -> str:
        return self.tag


class IngestHealthSnapshot(models.Model):
    """Daily per-source ingestion health metric row."""

    id = models.BigAutoField(primary_key=True)
    captured_at = models.DateTimeField(db_index=True)
    source_id = models.CharField(max_length=64, db_index=True)
    metric = models.CharField(max_length=64)
    value = models.DecimalField(max_digits=10, decimal_places=4)
    alert_threshold_breached = models.BooleanField(default=False)

    class Meta:
        app_label = "grants_ingest"

    def __str__(self) -> str:
        return f"{self.source_id}/{self.metric}@{self.captured_at}"
