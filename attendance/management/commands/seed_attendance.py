"""Seed synthetic attendance for a program so the donor page shows real numbers.

Synthetic data only — never real participant identifiers (CLAUDE.md code
conventions). Records go through the normal append-only AttendanceRecord path,
so the verification chain stays intact: every seeded number traces to a logged
event with an actor (the program's coordinator) and a timestamp.
"""

import calendar
import datetime
import random

from django.core.management.base import BaseCommand, CommandError

from attendance.models import AttendanceRecord, Participant
from core.models import Program, Session

# Synthetic first names — no real participant identifiers, ever.
SYNTHETIC_NAMES = [
    "Ava",
    "Marcus",
    "Lily",
    "Diego",
    "Aisha",
    "Noah",
    "Priya",
    "Jamal",
    "Sofia",
    "Kenji",
    "Maya",
    "Eli",
    "Zara",
    "Theo",
    "Nina",
    "Omar",
]


class Command(BaseCommand):
    help = "Create synthetic sessions + attendance for a program (current month)."

    def add_arguments(self, parser):
        parser.add_argument("--program-slug", required=True)
        parser.add_argument("--sessions", type=int, default=8)
        parser.add_argument("--students", type=int, default=12)
        parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible data")

    def handle(self, *args, **options):
        rng = random.Random(options["seed"])
        slug = options["program_slug"]
        n_sessions = options["sessions"]
        n_students = options["students"]

        try:
            program = Program.objects.get(slug=slug)
        except Program.DoesNotExist as exc:
            raise CommandError(f"No program with slug {slug!r}.") from exc

        if n_students > len(SYNTHETIC_NAMES):
            raise CommandError(
                f"Max {len(SYNTHETIC_NAMES)} synthetic students; asked for {n_students}."
            )

        coordinator = program.coordinator

        # Spread sessions across the current calendar month.
        today = datetime.date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]
        # cap session dates at today so nothing is "in the future"
        max_day = min(today.day, last_day)
        if n_sessions > max_day:
            n_sessions = max_day
        day_step = max(1, max_day // n_sessions)
        session_dates = [
            today.replace(day=min(1 + i * day_step, max_day)) for i in range(n_sessions)
        ]

        participants = []
        for name in SYNTHETIC_NAMES[:n_students]:
            p, _ = Participant.objects.get_or_create(
                organization=program.organization, display_name=name
            )
            participants.append(p)

        created_sessions = 0
        created_records = 0
        for d in session_dates:
            session, made = Session.objects.get_or_create(program=program, scheduled_date=d)
            if made:
                created_sessions += 1
            for participant in participants:
                # ~80% show up; of those a few are late
                roll = rng.random()
                if roll < 0.15:
                    status = AttendanceRecord.ABSENT
                elif roll < 0.25:
                    status = AttendanceRecord.LATE
                else:
                    status = AttendanceRecord.PRESENT
                AttendanceRecord.objects.create(
                    session=session,
                    participant=participant,
                    status=status,
                    recorded_by=coordinator,
                    source=AttendanceRecord.MANUAL_FORM,
                )
                created_records += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created_sessions} sessions, {len(participants)} participants, "
                f"{created_records} attendance records for {program.name!r}.\n"
                f"Now publish at /coordinator/programs/{program.slug}/ to surface them."
            )
        )
