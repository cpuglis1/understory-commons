"""Print basic ingest health metrics."""

from django.core.management.base import BaseCommand

from grants_ingest.models import CorpusEvent, Funder, HistoricalGrant
from grants_ingest.opportunity import OpportunityInstance


class Command(BaseCommand):
    help = "Print basic ingest health metrics."

    def handle(self, *args, **options):
        funder_count = Funder.objects.count()
        grant_count = HistoricalGrant.objects.count()
        unresolved_grants = HistoricalGrant.objects.filter(recipient_id__isnull=True).count()
        event_count = CorpusEvent.objects.count()
        last_event_id = (
            CorpusEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
        )
        opp_total = OpportunityInstance.objects.count()
        opp_unlinked = OpportunityInstance.objects.filter(funder__isnull=True).count()

        self.stdout.write("=== ingest health ===")
        self.stdout.write(f"funders:              {funder_count}")
        self.stdout.write(f"historical_grants:    {grant_count}")
        self.stdout.write(f"unresolved_grants:    {unresolved_grants}")
        self.stdout.write(f"corpus_events:        {event_count}")
        self.stdout.write(f"last_event_id:        {last_event_id}")
        if grant_count:
            rate = (grant_count - unresolved_grants) / grant_count * 100
            self.stdout.write(f"grant_resolution_rate:{rate:.1f}%")
        else:
            self.stdout.write("grant_resolution_rate:n/a")

        self.stdout.write(f"opportunities_total:  {opp_total}")
        self.stdout.write(f"opportunities_unlinked:{opp_unlinked}")

        # Per-source opportunity counts
        from django.db.models import Count

        per_source = (
            OpportunityInstance.objects.values("source_id")
            .annotate(count=Count("id"))
            .order_by("source_id")
        )
        for row in per_source:
            sid = row["source_id"] or "(no source)"
            self.stdout.write(f"  {sid}: {row['count']}")
