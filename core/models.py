import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def _unique_slug(name: str, model_class, exclude_pk=None) -> str:
    """Generate a URL-safe slug from *name*, appending -2/-3/… on collision."""
    base = slugify(name) or "program"
    slug = base
    n = 1
    qs = model_class.objects.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    while qs.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


class Organization(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=200, blank=True)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = _unique_slug(self.name, Organization, exclude_pk=self.pk)
        super().save(*args, **kwargs)


class Program(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="programs",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    summary = models.TextField(blank=True)
    site_label = models.CharField(max_length=200, blank=True)
    coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="coordinated_programs",
        limit_choices_to={"role": "coordinator"},
    )
    facilitators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="core.ProgramFacilitator",
        related_name="facilitated_programs",
        limit_choices_to={"role": "facilitator"},
        blank=True,
    )
    is_archived = models.BooleanField(default=False)

    # Session-guide pay defaults (set once at setup; see the session-guide ADR).
    # The default length feeds pay-prep math; the default facilitator pre-fills the
    # wrap screen's Facilitator of Record.
    default_session_length_minutes = models.PositiveIntegerField(default=90)
    default_facilitator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_for_programs",
        limit_choices_to={"role": "facilitator"},
    )

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = _unique_slug(self.name, Program, exclude_pk=self.pk)
        super().save(*args, **kwargs)

    def clean(self) -> None:
        if (
            self.coordinator_id
            and self.organization_id
            and self.coordinator.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Coordinator must belong to the same organization as the program."
            )


class ProgramFacilitator(models.Model):
    """Through-model for Program.facilitators carrying the per-(program, facilitator)
    pay rate (see the session-guide ADR, D1/D2).

    Rate lives on the assignment, not on the program or the person, so a senior lead
    and a junior helper can be paid differently in the same program. ``hourly_rate_cents``
    is nullable — an unset rate is *not* $0; pay-prep flags it. Money is integer cents.

    Plain ``Model`` (not ``TimestampedModel``) and ``db_table``/``db_column`` adopt the
    existing auto-created M2M table without data loss; the migration uses
    ``SeparateDatabaseAndState`` to keep its rows.
    """

    program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        related_name="facilitator_links",
    )
    facilitator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_column="user_id",
        related_name="program_links",
        limit_choices_to={"role": "facilitator"},
    )
    hourly_rate_cents = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "core_program_facilitators"
        unique_together = (("program", "facilitator"),)

    def __str__(self) -> str:
        return f"{self.facilitator} @ {self.program}"


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


class ProfileSnapshot(TimestampedModel):
    """Append-only, versioned, published projection of a program's verified metrics.

    A PUBLISHED snapshot is immutable. Re-publishing creates a superseding version.
    Withdrawal is a new WITHDRAWN version — never a delete or mutation.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (PUBLISHED, "Published"),
        (WITHDRAWN, "Withdrawn"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        related_name="snapshots",
    )
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="published_snapshots",
    )
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
    )
    payload = models.JSONField(default=dict)
    coverage_start = models.DateField()
    coverage_end = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["program", "version"],
                name="unique_snapshot_version_per_program",
            )
        ]

    def __str__(self) -> str:
        return f"{self.program} v{self.version} ({self.status})"

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            db_status = ProfileSnapshot.objects.values_list("status", flat=True).get(pk=self.pk)
            if db_status == self.PUBLISHED:
                raise ValueError(
                    "ProfileSnapshot is immutable once published; "
                    "create a new version to update."
                )
        super().save(*args, **kwargs)
