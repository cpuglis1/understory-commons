"""Funder and Program registry models.

These are materialized rows derived from CorpusEvent replays. They can be
rebuilt at any time by calling materialize.apply_events(since_event_id=0).
No rows from these models are produced in slice 1's irs_990pf/propublica_np
adapters for Program and ProgramAlias — those models ship now so the FK
from OpportunityInstance is satisfied when later slices land.
"""

import uuid

from django.db import models

from core.models import TimestampedModel


class FunderType(models.TextChoices):
    PRIVATE_FOUNDATION = "private_foundation", "Private Foundation"
    COMMUNITY_FOUNDATION = "community_foundation", "Community Foundation"
    PUBLIC_CHARITY = "public_charity", "Public Charity"
    GOVT_FEDERAL = "govt_federal", "Federal Government"
    GOVT_STATE = "govt_state", "State Government"
    GOVT_LOCAL = "govt_local", "Local Government"
    CORPORATE = "corporate", "Corporate"
    UNITED_WAY = "united_way", "United Way"
    UNKNOWN = "unknown", "Unknown"


class ProgramType(models.TextChoices):
    PROJECT = "project", "Project"
    CAPACITY = "capacity", "Capacity"
    OPERATING = "operating", "Operating"
    SCHOLARSHIP = "scholarship", "Scholarship"
    CAPITAL = "capital", "Capital"
    UNKNOWN = "unknown", "Unknown"


class OpportunityStatus(models.TextChoices):
    OPEN = "open", "Open"
    UPCOMING = "upcoming", "Upcoming"
    CLOSED = "closed", "Closed"
    ROLLING = "rolling", "Rolling"
    UNREACHABLE = "unreachable", "Unreachable"
    PROVISIONALLY_WITHDRAWN = "provisionally_withdrawn", "Provisionally Withdrawn"
    WITHDRAWN = "withdrawn", "Withdrawn"


class Funder(TimestampedModel):
    """A grant-making organization in the funder registry."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ein = models.CharField(max_length=9, null=True, blank=True, unique=True, db_index=True)
    canonical_name = models.CharField(max_length=255)
    canonical_name_normalized = models.CharField(max_length=255, db_index=True)
    funder_type = models.CharField(
        max_length=32, choices=FunderType.choices, default=FunderType.UNKNOWN
    )
    accepts_unsolicited = models.BooleanField(null=True, blank=True)
    typical_award_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    typical_award_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.JSONField(default=dict)

    class Meta:
        app_label = "grants_ingest"

    def __str__(self) -> str:
        return self.canonical_name


class FunderAlias(TimestampedModel):
    """Alternative name for a Funder. Indexed for fast resolver lookups."""

    funder = models.ForeignKey(Funder, on_delete=models.CASCADE, related_name="aliases")
    raw = models.CharField(max_length=255)
    normalized = models.CharField(max_length=255, db_index=True)

    class Meta:
        app_label = "grants_ingest"
        unique_together = [("funder", "normalized")]

    def __str__(self) -> str:
        return f"{self.raw} → {self.funder}"


class Program(TimestampedModel):
    """A named grant program within a Funder."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    funder = models.ForeignKey(Funder, on_delete=models.CASCADE, related_name="programs")
    canonical_name = models.CharField(max_length=255)
    canonical_name_normalized = models.CharField(max_length=255, db_index=True)

    class Meta:
        app_label = "grants_ingest"

    def __str__(self) -> str:
        return f"{self.funder} / {self.canonical_name}"


class ProgramAlias(TimestampedModel):
    """Alternative name for a Program."""

    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="aliases")
    raw = models.CharField(max_length=255)
    normalized = models.CharField(max_length=255, db_index=True)

    class Meta:
        app_label = "grants_ingest"
        unique_together = [("program", "normalized")]

    def __str__(self) -> str:
        return f"{self.raw} → {self.program}"
