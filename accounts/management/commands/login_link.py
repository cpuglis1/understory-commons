"""Mint a fresh one-time magic-link login URL (dev / demo convenience).

Magic links are single-use, so a saved URL goes stale once clicked. This command
mints a new one on demand — the fast path to "see the app" in any session.

    python manage.py login_link                 # first coordinator
    python manage.py login_link --email=a@b.org  # a specific user
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from accounts.services import magic_link_url, mint_magic_link


class Command(BaseCommand):
    help = "Print a fresh magic-link login URL for a coordinator (dev/demo only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email", default=None, help="User email; defaults to the first coordinator."
        )

    def handle(self, *args, **options):
        email = options["email"]
        if email:
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist as exc:
                raise CommandError(f"No user with email {email!r}.") from exc
        else:
            user = User.objects.filter(role=User.COORDINATOR).order_by("email").first()
            if user is None:
                raise CommandError("No coordinator exists yet — run bootstrap_org first.")

        token = mint_magic_link(user=user, created_by=user)
        self.stdout.write(self.style.SUCCESS(magic_link_url(token)))
        self.stdout.write(
            f"  (for {user.display_name} <{user.email}>; one-time, expires in 7 days)"
        )
