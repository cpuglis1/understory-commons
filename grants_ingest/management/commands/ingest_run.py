"""Run a single adapter end-to-end: fetch -> store -> events -> materialize."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError

from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.adapters.irs_990pf import IRS990PFAdapter
from grants_ingest.adapters.propublica_np import ProPublicaNPAdapter
from grants_ingest.materialize import apply_events
from grants_ingest.models import Funder
from grants_ingest.storage import get_object_store

logger = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "seeds"


class Command(BaseCommand):
    help = "Run one adapter end-to-end: fetch, store, log events, materialize."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, choices=["propublica_np", "irs_990pf"])
        parser.add_argument("--seed-list", default=str(SEEDS_DIR / "dmv_foundations.yml"))
        parser.add_argument(
            "--from-seed-list",
            action="store_true",
            help="For irs_990pf: pull XMLs for EINs in the seed list.",
        )
        parser.add_argument(
            "--from-funders",
            action="store_true",
            help="For irs_990pf: pull XMLs for all Funders in the DB.",
        )
        parser.add_argument(
            "--all-filings",
            action="store_true",
            help="For irs_990pf: fetch every filing, not just the most recent.",
        )

    def handle(self, *args, **options):
        source = options["source"]
        store = get_object_store()
        event_log = EventLogWriter(
            source_id=source,
            actor=f"system:{source}_v0.1.0",
        )

        if source == "propublica_np":
            eins = _load_eins(options["seed_list"])
            adapter = ProPublicaNPAdapter(store=store, event_log=event_log, seed_eins=eins)
        elif source == "irs_990pf":
            filing_urls = _build_filing_urls(
                options["seed_list"],
                from_seed_list=options["from_seed_list"],
                from_funders=options["from_funders"],
                all_filings=options["all_filings"],
            )
            adapter = IRS990PFAdapter(store=store, event_log=event_log, filing_urls=filing_urls)
        else:
            raise CommandError(f"Unknown source: {source}")

        self.stdout.write(f"Running {source}...")
        result = adapter.run()
        self.stdout.write(
            f"Done: fetched={result.fetched} stored_new={result.stored_new} "
            f"parse_errors={result.parse_errors} robots_blocked={result.robots_blocked}"
        )
        if result.errors:
            for err in result.errors:
                self.stderr.write(f"  ERROR: {err}")

        self.stdout.write("Materializing events...")
        apply_events()
        self.stdout.write("Done.")


def _load_eins(seed_list_path: str) -> list[str]:
    path = Path(seed_list_path)
    if not path.exists():
        logger.warning("Seed list not found: %s — running with empty list", path)
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    return [str(entry["ein"]).replace("-", "") for entry in (data or []) if entry.get("ein")]


def _build_filing_urls(
    seed_list_path: str,
    from_seed_list: bool,
    from_funders: bool,
    all_filings: bool,
) -> list[dict]:
    if from_funders:
        eins = list(Funder.objects.exclude(ein__isnull=True).values_list("ein", flat=True))
    else:
        eins = _load_eins(seed_list_path)

    filing_urls = []
    for funder in Funder.objects.filter(ein__in=eins):
        filings = funder.notes.get("filings_index", [])
        if not all_filings and filings:
            filings = filings[:1]
        for entry in filings:
            url = entry.get("xml_url")
            if url:
                filing_urls.append({"ein": funder.ein, "url": url, "year": entry.get("year")})
    return filing_urls
