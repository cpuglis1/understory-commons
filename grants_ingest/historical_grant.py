"""HistoricalGrant — one row per grant recorded in a 990-PF Part XV-1 filing."""

import uuid

from django.db import models

from .raw_record import RawRecord
from .registry import Funder


class HistoricalGrant(models.Model):
    """A single grant payment extracted from an IRS 990-PF filing.

    Idempotency: re-parsing the same XML cannot produce duplicate rows because
    (source_record, recipient_name_raw, amount, tax_year) is unique.

    recipient_id is a plain UUIDField rather than a ForeignKey because the
    target org-registry table does not exist yet. Switching to a real FK is
    a later migration once the recipient-resolution component lands.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    funder = models.ForeignKey(Funder, on_delete=models.CASCADE, related_name="historical_grants")
    funder_ein = models.CharField(max_length=9, db_index=True)
    tax_year = models.IntegerField(db_index=True)
    recipient_name_raw = models.CharField(max_length=512)
    recipient_address_raw = models.TextField(blank=True, default="")
    recipient_ein = models.CharField(max_length=9, blank=True, default="", db_index=True)
    recipient_id = models.UUIDField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    purpose = models.TextField(blank=True, default="")
    relationship_flag = models.CharField(max_length=64, blank=True, default="")
    source_record = models.ForeignKey(
        RawRecord, on_delete=models.PROTECT, related_name="historical_grants"
    )

    class Meta:
        app_label = "grants_ingest"
        unique_together = [("source_record", "recipient_name_raw", "amount", "tax_year")]

    def __str__(self) -> str:
        return f"{self.funder_ein} → {self.recipient_name_raw} ({self.tax_year}) ${self.amount}"
