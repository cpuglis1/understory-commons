"""Dump unresolved HistoricalGrant recipient rows for manual review."""

import csv
import sys

from django.core.management.base import BaseCommand

from grants_ingest.models import HistoricalGrant


class Command(BaseCommand):
    help = "Export unresolved HistoricalGrant rows (recipient_id=None) for manual review."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            choices=["csv", "stdout"],
            default="stdout",
        )

    def handle(self, *args, **options):
        qs = HistoricalGrant.objects.filter(recipient_id__isnull=True).select_related(
            "funder", "source_record"
        )
        rows = qs.values(
            "id",
            "funder__ein",
            "funder__canonical_name",
            "tax_year",
            "recipient_name_raw",
            "recipient_ein",
            "amount",
        )

        if options["output"] == "csv":
            writer = csv.DictWriter(
                sys.stdout,
                fieldnames=[
                    "id",
                    "funder__ein",
                    "funder__canonical_name",
                    "tax_year",
                    "recipient_name_raw",
                    "recipient_ein",
                    "amount",
                ],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        else:
            count = 0
            for row in rows:
                self.stdout.write(
                    f"{row['funder__ein']} | {row['tax_year']} | "
                    f"{row['recipient_name_raw']} | ${row['amount']}"
                )
                count += 1
            self.stdout.write(f"\nTotal unresolved: {count}")
