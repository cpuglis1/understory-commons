"""Run a single adapter end-to-end: fetch -> store -> events -> materialize."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError

from grants_ingest.adapters.dc_cah import DCAHAdapter
from grants_ingest.adapters.dc_eventsdc import DCEventsDCAdapter
from grants_ingest.adapters.dc_humanitiesdc import DCHumanitiesDCAdapter
from grants_ingest.adapters.dc_moca import DCMOCAAdapter
from grants_ingest.adapters.dc_ost import DCOSTAdapter
from grants_ingest.adapters.event_log import EventLogWriter
from grants_ingest.adapters.grants_gov import GrantsGovAdapter
from grants_ingest.adapters.irs_990pf import IRS990PFAdapter
from grants_ingest.adapters.propublica_np import ProPublicaNPAdapter
from grants_ingest.materialize import apply_events
from grants_ingest.storage import get_object_store

logger = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "seeds"


class Command(BaseCommand):
    help = "Run one adapter end-to-end: fetch, store, log events, materialize."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            choices=[
                "propublica_np",
                "irs_990pf",
                "grants_gov",
                "gov_dc_ost",
                "gov_dc_moca",
                "gov_dc_cah",
                "dc_humanitiesdc",
                "dc_eventsdc",
            ],
        )
        parser.add_argument("--seed-list", default=str(SEEDS_DIR / "dmv_foundations.yml"))
        parser.add_argument(
            "--months-back",
            type=int,
            default=3,
            help="For irs_990pf: number of monthly batch zips to scan (default 3).",
        )

    def handle(self, *args, **options):
        source = options["source"]
        store = get_object_store()
        event_log = EventLogWriter(
            source_id=source,
            actor=f"system:{source}_v0.1.0",
        )

        adapter = _build_adapter(source, store, event_log, options)

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


def _build_adapter(source: str, store, event_log, options):
    if source == "propublica_np":
        eins = _load_eins(options["seed_list"])
        return ProPublicaNPAdapter(store=store, event_log=event_log, seed_eins=eins)
    if source == "irs_990pf":
        eins = _load_eins(options["seed_list"])
        return IRS990PFAdapter(
            store=store,
            event_log=event_log,
            seed_eins=eins,
            months_back=options["months_back"],
        )
    if source == "grants_gov":
        return GrantsGovAdapter(store=store, event_log=event_log)
    if source == "gov_dc_ost":
        return DCOSTAdapter(store=store, event_log=event_log)
    if source == "gov_dc_moca":
        return DCMOCAAdapter(store=store, event_log=event_log)
    if source == "gov_dc_cah":
        return DCAHAdapter(store=store, event_log=event_log)
    if source == "dc_humanitiesdc":
        return DCHumanitiesDCAdapter(store=store, event_log=event_log)
    if source == "dc_eventsdc":
        return DCEventsDCAdapter(store=store, event_log=event_log)
    raise CommandError(f"Unknown source: {source}")


def _load_eins(seed_list_path: str) -> list[str]:
    path = Path(seed_list_path)
    if not path.exists():
        logger.warning("Seed list not found: %s — running with empty list", path)
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    return [str(entry["ein"]).replace("-", "") for entry in (data or []) if entry.get("ein")]
