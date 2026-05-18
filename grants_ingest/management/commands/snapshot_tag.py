"""Record a CorpusSnapshot row capturing event log position + manifest hash."""

import hashlib

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from grants_ingest.models import CorpusEvent, CorpusSnapshot
from grants_ingest.storage import get_object_store


class Command(BaseCommand):
    help = "Tag a corpus snapshot: captures max(event.id) and manifest hash."

    def add_arguments(self, parser):
        parser.add_argument("tag", help="Snapshot tag, e.g. 'corpus-2026-05-18'")
        parser.add_argument("--notes", default="")

    def handle(self, *args, **options):
        tag = options["tag"]
        if CorpusSnapshot.objects.filter(tag=tag).exists():
            raise CommandError(f"Snapshot tag '{tag}' already exists.")

        max_event_id = CorpusEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0

        store = get_object_store()
        manifest_shas = sorted(store.iter_manifest())
        manifest_hash = hashlib.sha256("\n".join(manifest_shas).encode()).hexdigest()

        CorpusSnapshot.objects.create(
            tag=tag,
            event_log_position=max_event_id,
            object_store_manifest_ref=manifest_hash,
            created_at=timezone.now(),
            notes=options["notes"],
        )
        self.stdout.write(
            f"Snapshot '{tag}' created: event_log_position={max_event_id} manifest={manifest_hash[:12]}..."
        )
