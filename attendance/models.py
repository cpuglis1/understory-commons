import uuid

from django.conf import settings
from django.db import models

from core.models import Organization, Session, TimestampedModel


class Participant(TimestampedModel):
    """A person who attends a program session.

    PII boundary: display_name is the only personal field. No first/last
    split, no contact info, no DOB. Any addition crosses the PII boundary
    and requires Opus-tier review.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="participants",
    )
    display_name = models.CharField(max_length=200)
    merged_into = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="merged_from",
    )

    def __str__(self) -> str:
        return self.display_name


class AttendanceRecord(models.Model):
    """Append-only record of a participant's attendance at a session.

    Corrections are written as new records; reporting takes the latest
    record per (session, participant) ordered by recorded_at.
    recorded_by + recorded_at form the non-repudiable verification chain.
    """

    PRESENT = "present"
    LATE = "late"
    ABSENT = "absent"
    EXCUSED = "excused"
    STATUS_CHOICES = [
        (PRESENT, "Present"),
        (LATE, "Late"),
        (ABSENT, "Absent"),
        (EXCUSED, "Excused"),
    ]

    LLM_PARSE = "llm_parse"
    MANUAL_FORM = "manual_form"
    SOURCE_CHOICES = [
        (LLM_PARSE, "LLM parse"),
        (MANUAL_FORM, "Manual form"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        Session,
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_attendance",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    raw_input = models.TextField(blank=True)
    llm_request_id = models.CharField(max_length=128, blank=True)
    submission_idempotency_key = models.CharField(max_length=64, blank=True, db_index=True)

    def __str__(self) -> str:
        return f"{self.participant} — {self.status} @ {self.session}"

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValueError("AttendanceRecord is append-only and cannot be updated.")
        super().save(*args, **kwargs)
