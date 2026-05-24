"""Re-parse existing DC opportunity rows through the structured extractors.

Does NOT re-fetch. Reads archived raw bytes from the object store, runs
the deterministic extractors, emits OPPORTUNITY_UPDATED events, and lets
the materializer apply them to existing rows.

Idempotent: running twice produces the same result (later OPPORTUNITY_UPDATED
events overwrite the same field values).

Usage:
    python manage.py backfill_structured_fields --source gov_dc_moca
    python manage.py backfill_structured_fields --source gov_dc_cah
    python manage.py backfill_structured_fields --all-dc
"""

from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from grants_ingest.adapters.dc_html_util import extract_moca_agency
from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.extraction.structured import (
    AGENCY_SUBJECT_AREAS,
    augment_subject_areas_from_title,
    extract_award_range,
    extract_budget_cap,
    extract_dc_agency,
    extract_deadline,
    extract_org_type,
    extract_status,
    html_to_text,
)
from grants_ingest.materialize import apply_events
from grants_ingest.opportunity import OpportunityInstance
from grants_ingest.raw_record import RawRecord
from grants_ingest.storage import get_object_store

logger = logging.getLogger(__name__)

# Source-level configuration for each DC adapter.
# subject_areas: base codes applied to every row from this source.
# check_budget_cap: whether to scan for budget eligibility cap.
# moca_body_agency: whether to run body-level DC agency extraction.
_SOURCE_CONFIG: dict[str, dict] = {
    "gov_dc_ost": {
        "subject_areas": ["youth_development", "education", "out_of_school_time"],
        "check_budget_cap": False,
        "moca_body_agency": False,
    },
    "gov_dc_moca": {
        "subject_areas": ["general"],
        "check_budget_cap": False,
        "moca_body_agency": True,
    },
    "gov_dc_cah": {
        "subject_areas": ["arts", "humanities"],
        "check_budget_cap": False,
        "moca_body_agency": False,
    },
    "dc_humanitiesdc": {
        "subject_areas": ["humanities"],
        "check_budget_cap": True,
        "moca_body_agency": False,
    },
    "dc_eventsdc": {
        "subject_areas": ["youth_development", "arts", "athletics"],
        "check_budget_cap": False,
        "moca_body_agency": False,
    },
}

_ALL_DC_SOURCES = list(_SOURCE_CONFIG.keys())


class Command(BaseCommand):
    help = "Backfill structured fields on existing DC OpportunityInstance rows."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--source",
            choices=_ALL_DC_SOURCES,
            help="Single DC source to backfill.",
        )
        group.add_argument(
            "--all-dc",
            action="store_true",
            help="Backfill all 5 DC sources.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be emitted without writing events.",
        )

    def handle(self, *args, **options):
        sources = _ALL_DC_SOURCES if options["all_dc"] else [options["source"]]
        dry_run = options["dry_run"]
        store = get_object_store()

        total_updated = 0
        total_skipped = 0

        for source_id in sources:
            cfg = _SOURCE_CONFIG[source_id]
            self.stderr.write(f"\n=== Backfilling {source_id} ===")

            opps = OpportunityInstance.objects.filter(source_id=source_id).prefetch_related(
                "source_records"
            )
            count = opps.count()
            self.stderr.write(f"  {count} OpportunityInstance rows found")

            event_log = EventLogWriter(
                source_id=source_id,
                actor="system:backfill_structured_fields",
            )

            # Record the current high-water mark so we only materialize
            # the events we just emitted, not the full 300K+ event history.
            last_event_before = (
                CorpusEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
            )

            updated = skipped = 0
            for opp in opps:
                # Find the primary HTML record: prefer the one whose fetch_url
                # matches the opportunity's external_id (not attachment PDFs).
                html_record = _pick_html_record(opp)
                if html_record is None:
                    logger.warning(
                        "backfill: no HTML record for %s/%s, skipping",
                        source_id,
                        opp.external_id,
                    )
                    skipped += 1
                    continue

                try:
                    body = store.get(html_record.content_sha)
                except Exception as exc:
                    logger.warning(
                        "backfill: could not load raw bytes for %s: %s",
                        html_record.content_sha,
                        exc,
                    )
                    skipped += 1
                    continue

                fields = _extract_fields(
                    body=body,
                    title=opp.title,
                    cfg=cfg,
                    funder_name_raw=opp.funder_name_raw,
                )

                if not fields:
                    skipped += 1
                    continue

                payload: dict[str, Any] = {
                    "source_id": source_id,
                    "external_id": opp.external_id,
                    **fields,
                }

                if dry_run:
                    self.stdout.write(f"  [dry-run] {opp.external_id}: {list(fields.keys())}")
                else:
                    event_log.append(
                        CorpusEventType.OPPORTUNITY_UPDATED,
                        content_sha=html_record.content_sha,
                        payload=payload,
                    )
                updated += 1

            if not dry_run and updated > 0:
                self.stderr.write(f"  Materializing {updated} OPPORTUNITY_UPDATED events...")
                apply_events(since_event_id=last_event_before)

            self.stderr.write(f"  Updated: {updated}  Skipped: {skipped}")
            total_updated += updated
            total_skipped += skipped

        self.stderr.write(
            f"\nBackfill complete. Total updated: {total_updated}  Total skipped: {total_skipped}"
        )


def _pick_html_record(opp: OpportunityInstance) -> RawRecord | None:
    """Return the HTML raw record most likely to be the primary page, not a PDF."""
    records = list(opp.source_records.all())
    if not records:
        return None
    # Prefer records with text/html mime type or whose URL doesn't end in .pdf/.docx
    html_records = [
        r
        for r in records
        if r.mime_type.startswith("text/html")
        or not r.fetch_url.lower().endswith((".pdf", ".docx"))
    ]
    if html_records:
        return html_records[0]
    return records[0]


def _extract_fields(
    body: bytes,
    title: str,
    cfg: dict,
    funder_name_raw: str,
) -> dict[str, Any]:
    """Run extractors and return a dict of non-None extracted fields."""
    text = html_to_text(body)
    now = timezone.now().replace(tzinfo=None)
    fields: dict[str, Any] = {}

    deadline = extract_deadline(body, text)
    if deadline is not None:
        deadline_aware = deadline.replace(tzinfo=UTC)
        fields["application_close_at"] = deadline_aware.isoformat()
        fields["status"] = extract_status(deadline, now)
    else:
        fields["status"] = "open"

    award_min, award_max = extract_award_range(body, text)
    if award_min is not None:
        fields["award_min"] = str(award_min)
    if award_max is not None:
        fields["award_max"] = str(award_max)

    org_type = extract_org_type(body, text)
    eligibility: dict[str, Any] = {}
    if org_type:
        eligibility["org_type"] = org_type
    if cfg["check_budget_cap"]:
        cap = extract_budget_cap(text)
        if cap is not None:
            eligibility["budget_max"] = int(cap)
    if eligibility:
        fields["eligibility"] = eligibility

    # MOCA: try to resolve agency from body text
    agency: str | None = None
    if cfg["moca_body_agency"]:
        agency = extract_moca_agency(title) or extract_dc_agency(text) or None
        if agency:
            fields["funder_name_raw"] = agency

    subject_areas = list(cfg["subject_areas"])
    if agency:
        for code in AGENCY_SUBJECT_AREAS.get(agency, []):
            if code not in subject_areas:
                subject_areas.append(code)
    subject_areas = augment_subject_areas_from_title(title, subject_areas)
    if subject_areas:
        fields["subject_areas"] = subject_areas

    return fields
