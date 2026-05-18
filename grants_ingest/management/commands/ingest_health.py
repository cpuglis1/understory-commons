"""Emit ingest health metrics (stub — zeroed until alert thresholds are defined)."""

from django.core.management.base import BaseCommand

from grants_ingest.models import CorpusEvent, Funder, HistoricalGrant


class Command(BaseCommand):
    help = "Print basic ingest health metrics."

    def handle(self, *args, **options):
        funder_count = Funder.objects.count()
        grant_count = HistoricalGrant.objects.count()
        unresolved = HistoricalGrant.objects.filter(recipient_id__isnull=True).count()
        event_count = CorpusEvent.objects.count()
        last_event_id = (
            CorpusEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
        )

        self.stdout.write("=== ingest health ===")
        self.stdout.write(f"funders:          {funder_count}")
        self.stdout.write(f"historical_grants:{grant_count}")
        self.stdout.write(f"unresolved:       {unresolved}")
        self.stdout.write(f"corpus_events:    {event_count}")
        self.stdout.write(f"last_event_id:    {last_event_id}")
        self.stdout.write(
            f"resolution_rate:  " f"{(grant_count - unresolved) / grant_count * 100:.1f}%"
            if grant_count
            else "resolution_rate:  n/a"
        )
