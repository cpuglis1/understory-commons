"""Resolve unresolved funder links on HistoricalGrant and OpportunityInstance rows."""

from django.core.management.base import BaseCommand

from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.corpus_event import CorpusEventType
from grants_ingest.models import HistoricalGrant
from grants_ingest.opportunity import OpportunityInstance
from grants_ingest.registry import Funder
from grants_ingest.resolution import normalize_funder_name, resolve_funder


class Command(BaseCommand):
    help = "Resolve unresolved funder links using the entity resolver."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="", help="Filter by source_id.")
        parser.add_argument(
            "--target",
            default="historical_grants",
            choices=["historical_grants", "opportunities", "all"],
            help="Which rows to resolve (default: historical_grants).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print matches without writing to the DB.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        target = options["target"]
        event_log = EventLogWriter(source_id="resolver", actor="system:resolver_v0.1.0")

        if target in ("historical_grants", "all"):
            r, m = _resolve_historical_grants(options["source"], dry_run, event_log, self.stdout)
            self.stdout.write(f"historical_grants — resolved: {r}  missed: {m}")

        if target in ("opportunities", "all"):
            r, m = _resolve_opportunities(options["source"], dry_run, event_log, self.stdout)
            self.stdout.write(f"opportunities     — resolved: {r}  missed: {m}")


def _resolve_historical_grants(source: str, dry_run: bool, event_log, stdout) -> tuple[int, int]:
    qs = HistoricalGrant.objects.filter(recipient_id__isnull=True)
    if source:
        qs = qs.filter(source_record__source_id=source)

    resolved = 0
    missed = 0
    for grant in qs.select_related("funder"):
        result = resolve_funder(grant.recipient_name_raw, ein=grant.recipient_ein or None)
        if result.funder_id and not dry_run:
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
            stdout.write(
                f"[dry-run] {grant.recipient_name_raw} -> {result.matched_funder} ({result.confidence})"
            )
            resolved += 1
        else:
            missed += 1
    return resolved, missed


def _resolve_opportunities(source: str, dry_run: bool, event_log, stdout) -> tuple[int, int]:
    qs = OpportunityInstance.objects.filter(funder__isnull=True)
    if source:
        qs = qs.filter(source_id=source)

    resolved = 0
    missed = 0
    for opp in qs:
        result = resolve_funder(opp.funder_name_raw)
        if result.funder_id:
            if not dry_run:
                OpportunityInstance.objects.filter(pk=opp.pk).update(funder_id=result.funder_id)
                event_log.append(
                    CorpusEventType.RESOLVED,
                    payload={
                        "target": "opportunity",
                        "external_id": opp.external_id,
                        "funder_name_raw": opp.funder_name_raw,
                        "funder_id": result.funder_id,
                        "confidence": result.confidence,
                    },
                )
            else:
                stdout.write(
                    f"[dry-run] {opp.external_id}: {opp.funder_name_raw} -> {result.matched_funder} ({result.confidence})"
                )
            resolved += 1
        elif opp.source_id == "grants_gov" and opp.funder_name_raw:
            # Auto-create stub Funder for grants_gov misses (Q2 decision)
            if not dry_run:
                funder, created = Funder.objects.get_or_create(
                    canonical_name_normalized=normalize_funder_name(opp.funder_name_raw),
                    defaults={
                        "canonical_name": opp.funder_name_raw,
                        "notes": {"auto_created_from": "grants_gov"},
                    },
                )
                OpportunityInstance.objects.filter(pk=opp.pk).update(funder_id=funder.id)
                event_log.append(
                    CorpusEventType.RESOLVED,
                    payload={
                        "target": "opportunity",
                        "external_id": opp.external_id,
                        "funder_name_raw": opp.funder_name_raw,
                        "funder_id": str(funder.id),
                        "confidence": "auto_created",
                        "created": created,
                    },
                )
            else:
                stdout.write(
                    f"[dry-run] {opp.external_id}: would auto-create funder '{opp.funder_name_raw}'"
                )
            resolved += 1
        else:
            missed += 1
    return resolved, missed
