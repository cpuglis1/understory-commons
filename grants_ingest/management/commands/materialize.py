"""Re-apply CorpusEvents to registry tables. Idempotent."""

from django.core.management.base import BaseCommand

from grants_ingest.materialize import apply_events


class Command(BaseCommand):
    help = "Re-apply CorpusEvents to derived registry tables. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--since-event-id",
            type=int,
            default=0,
            help="Only process events with id > this value.",
        )

    def handle(self, *args, **options):
        since = options["since_event_id"]
        self.stdout.write(f"Materializing events since id={since}...")
        last_id = apply_events(since_event_id=since)
        self.stdout.write(f"Done. Last event id applied: {last_id}")
