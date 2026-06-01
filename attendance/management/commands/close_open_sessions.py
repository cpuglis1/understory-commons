"""The Midnight Rule: auto-close any session left open past its day (session-guide ADR D6).

Run by cron at 11:59pm local (Eastern — see TIME_ZONE), so a facilitator who forgets to
wrap still gets a day that counts for pay:

    59 23 * * *  cd /app && python manage.py close_open_sessions

Idempotent (only touches still-open sessions), commits the program's default duration for
pay, stamps the default facilitator as Facilitator of Record (null is fine — pay-prep
flags it), and marks ``auto_closed``. It never fabricates a wrap note: an auto-closed
session has no note because nobody logged one.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Session


class Command(BaseCommand):
    help = "Close sessions left open past their scheduled date (the Midnight Rule)."

    def handle(self, *args, **options) -> None:
        today = timezone.localdate()
        now = timezone.now()

        open_sessions = Session.objects.filter(
            closed_at__isnull=True,
            scheduled_date__lte=today,  # leave future-dated sessions alone
        ).select_related("program", "program__default_facilitator")

        closed = 0
        for session in open_sessions:
            session.closed_at = now
            session.duration_minutes = session.program.default_session_length_minutes
            session.facilitator_of_record = session.program.default_facilitator
            session.auto_closed = True
            session.save()
            closed += 1

        self.stdout.write(self.style.SUCCESS(f"Auto-closed {closed} open session(s) for {today}."))
