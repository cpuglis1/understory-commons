import uuid

from django.db import models


class Organization(models.Model):
    """Minimal stub — TimestampedModel base and full fields added in Step 4."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.name
