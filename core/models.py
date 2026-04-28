import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Organization(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.name


class Program(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="programs",
    )
    name = models.CharField(max_length=200)
    site_label = models.CharField(max_length=200, blank=True)
    coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="coordinated_programs",
        limit_choices_to={"role": "coordinator"},
    )
    facilitators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="facilitated_programs",
        limit_choices_to={"role": "facilitator"},
        blank=True,
    )
    is_archived = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if (
            self.coordinator_id
            and self.organization_id
            and self.coordinator.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Coordinator must belong to the same organization as the program."
            )


class Session(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        related_name="sessions",
    )
    scheduled_date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["program", "scheduled_date"],
                name="unique_session_per_program_date",
            )
        ]

    def __str__(self) -> str:
        return f"{self.program} — {self.scheduled_date}"
