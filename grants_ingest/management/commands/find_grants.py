"""Search OpportunityInstance rows using a YAML filter profile.

Usage:
    python manage.py find_grants --profile profiles/dmv_youth_ed_sample.yaml
    python manage.py find_grants --profile profiles/dmv_youth_ed_sample.yaml --format json
    python manage.py find_grants --profile profiles/dmv_youth_ed_sample.yaml --format csv

Profile YAML keys (all optional):
  open_only: bool            — exclude rows with application_close_at in the past
  award_min_gte: int/float   — minimum award_min value
  award_max_lte: int/float   — maximum award_max value
  sources: [str, ...]        — restrict to these source_id values
  subject_areas: [str, ...]  — any subject_area code/text must match (OR)
  funder_name_contains: str  — case-insensitive substring match on funder_name_raw

Output formats: table (default), json, csv
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from grants_ingest.opportunity import OpportunityInstance


class Command(BaseCommand):
    help = "Filter OpportunityInstance rows using a YAML profile and print results."

    def add_arguments(self, parser):
        parser.add_argument("--profile", required=True, help="Path to YAML filter profile.")
        parser.add_argument(
            "--format",
            default="table",
            choices=["table", "json", "csv"],
            help="Output format (default: table).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=200,
            help="Maximum rows to return (default: 200).",
        )

    def handle(self, *args, **options):
        profile_path = Path(options["profile"])
        if not profile_path.exists():
            raise CommandError(f"Profile not found: {profile_path}")

        with open(profile_path) as f:
            profile = yaml.safe_load(f) or {}

        filters = profile.get("filters", profile)  # support both top-level and nested 'filters'
        qs = _build_queryset(filters)
        qs = qs.order_by("application_close_at", "title")[: options["limit"]]

        rows = list(
            qs.values(
                "external_id",
                "source_id",
                "title",
                "funder_name_raw",
                "application_close_at",
                "award_min",
                "award_max",
                "subject_areas",
            )
        )

        fmt = options["format"]
        if fmt == "json":
            self.stdout.write(_to_json(rows))
        elif fmt == "csv":
            _write_csv(rows, self.stdout)
        else:
            _write_table(rows, self.stdout)

        self.stderr.write(f"\n{len(rows)} result(s)")


def _build_queryset(filters: dict):
    qs = OpportunityInstance.objects.all()

    if filters.get("open_only"):
        now = timezone.now()
        # include rows with no close date (rolling) or close_date in the future
        from django.db.models import Q

        qs = qs.filter(Q(application_close_at__isnull=True) | Q(application_close_at__gte=now))

    if filters.get("award_min_gte") is not None:
        qs = qs.filter(award_min__gte=filters["award_min_gte"])

    if filters.get("award_max_lte") is not None:
        qs = qs.filter(award_max__lte=filters["award_max_lte"])

    sources = filters.get("sources") or []
    if sources:
        qs = qs.filter(source_id__in=sources)

    funder_fragment = filters.get("funder_name_contains") or ""
    if funder_fragment:
        qs = qs.filter(funder_name_raw__icontains=funder_fragment)

    subject_areas = filters.get("subject_areas") or []
    if subject_areas:
        # OR logic: keep row if any of the profile's subject_areas appear in the row's list
        from django.db.models import Q

        q = Q()
        for code in subject_areas:
            q |= Q(subject_areas__icontains=code)
        qs = qs.filter(q)

    return qs


_COLUMNS = [
    "external_id",
    "source_id",
    "title",
    "funder_name_raw",
    "application_close_at",
    "award_min",
    "award_max",
]


def _fmt_row(row: dict) -> dict:
    """Flatten/format a values() row for display."""
    close = row.get("application_close_at")
    return {
        "external_id": row.get("external_id", ""),
        "source_id": row.get("source_id", ""),
        "title": (row.get("title") or "")[:80],
        "funder": (row.get("funder_name_raw") or "")[:40],
        "close_date": close.strftime("%Y-%m-%d") if close else "",
        "award_min": str(row.get("award_min") or ""),
        "award_max": str(row.get("award_max") or ""),
    }


def _to_json(rows: list[dict]) -> str:
    out = []
    for row in rows:
        r = dict(row)
        if r.get("application_close_at"):
            r["application_close_at"] = r["application_close_at"].isoformat()
        if r.get("award_min") is not None:
            r["award_min"] = float(r["award_min"])
        if r.get("award_max") is not None:
            r["award_max"] = float(r["award_max"])
        out.append(r)
    return json.dumps(out, indent=2, default=str)


def _write_csv(rows: list[dict], stdout) -> None:
    display_rows = [_fmt_row(r) for r in rows]
    if not display_rows:
        return
    writer = csv.DictWriter(stdout, fieldnames=list(display_rows[0].keys()))
    writer.writeheader()
    writer.writerows(display_rows)


def _write_table(rows: list[dict], stdout) -> None:
    display_rows = [_fmt_row(r) for r in rows]
    if not display_rows:
        stdout.write("(no results)")
        return

    cols = list(display_rows[0].keys())
    widths = {c: max(len(c), max(len(r[c]) for r in display_rows)) for c in cols}

    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    stdout.write(header)
    stdout.write(sep)
    for row in display_rows:
        stdout.write("  ".join(row[c].ljust(widths[c]) for c in cols))
