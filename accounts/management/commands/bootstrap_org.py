from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from accounts.services import magic_link_url, mint_magic_link
from core.models import Organization


class Command(BaseCommand):
    help = "Create the first Organization + coordinator account and print a magic-link login URL."

    def add_arguments(self, parser):
        parser.add_argument("--org-name", required=True, help="Organization display name")
        parser.add_argument("--email", required=True, help="Coordinator email address")
        parser.add_argument("--name", required=True, help="Coordinator display name")

    def handle(self, *args, **options):
        org_name = options["org_name"].strip()
        email = options["email"].strip().lower()
        display_name = options["name"].strip()

        if not org_name:
            raise CommandError("--org-name must not be blank")
        if not email:
            raise CommandError("--email must not be blank")
        if not display_name:
            raise CommandError("--name must not be blank")

        if User.objects.filter(email=email).exists():
            raise CommandError(f"A user with email {email!r} already exists.")

        org = Organization.objects.create(name=org_name)
        user = User.objects.create_user(
            email=email,
            display_name=display_name,
            organization=org,
            role=User.COORDINATOR,
        )
        token = mint_magic_link(user=user, created_by=user)
        url = magic_link_url(token)

        self.stdout.write(self.style.SUCCESS(f"Created org:  {org.name} ({org.pk})"))
        self.stdout.write(self.style.SUCCESS(f"Created user: {user.display_name} <{user.email}>"))
        self.stdout.write(self.style.SUCCESS(f"\nLogin URL (expires in 7 days):\n{url}"))
