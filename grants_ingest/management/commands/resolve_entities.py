"""Run the entity resolver over unresolved HistoricalGrant recipient rows."""

from django.core.management.base import BaseCommand

from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.models import HistoricalGrant
from grants_ingest.resolution import resolve_funder


class Command(BaseCommand):
    help = "Resolve unresolved HistoricalGrant.recipient_id rows using the funder resolver."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="", help="Filter by source_id on the RawRecord.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print matches without writing to the DB.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        event_log = EventLogWriter(source_id="resolver", actor="system:resolver_v0.1.0")

        qs = HistoricalGrant.objects.filter(recipient_id__isnull=True)
        if options["source"]:
            qs = qs.filter(source_record__source_id=options["source"])

        resolved = 0
        missed = 0
        for grant in qs.select_related("funder"):
            result = resolve_funder(
                grant.recipient_name_raw,
                ein=grant.recipient_ein or None,
            )
            if result.funder_id and not dry_run:
                grant.recipient_id = result.funder_id
                HistoricalGrant.objects.filter(pk=grant.pk).update(recipient_id=result.funder_id)
                event_log.append(
                    CorpusEventType.RESOLVED,
                    payload={
                        "grant_id": str(grant.id),
                        "recipient_name_raw": grant.recipient_name_raw,
                        "funder_id": result.funder_id,
                        "confidence": result.confidence,
                    },
                )
                resolved += 1
            elif result.funder_id and dry_run:
                self.stdout.write(
                    f"[dry-run] {grant.recipient_name_raw} -> {result.matched_funder} ({result.confidence})"
                )
                resolved += 1
            else:
                missed += 1

        self.stdout.write(f"Resolved: {resolved}  Missed: {missed}")
