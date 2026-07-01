"""Guided first-run: create a superuser, the initial lab, and lab-owned roles.

    uv run python manage.py bootstrap_lab

Interactive by default; pass --noinput with the flags below for scripted setup.
Idempotent on the lab slug — re-running with an existing slug reuses that lab.
"""

import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.tenancy.models import Lab
from apps.tenancy.services import add_member, create_lab

User = get_user_model()


class Command(BaseCommand):
    help = "Create the first superuser and initial lab (with cloned template roles)."

    def add_arguments(self, parser):
        parser.add_argument("--email")
        parser.add_argument("--password")
        parser.add_argument("--lab-name")
        parser.add_argument("--lab-prefix")
        parser.add_argument(
            "--noinput",
            action="store_true",
            help="Do not prompt; require the flags above.",
        )

    def handle(self, *args, **opts):
        noinput = opts["noinput"]

        email = opts["email"] or self._prompt("Admin email", noinput)
        lab_name = opts["lab_name"] or self._prompt("Lab name", noinput)
        lab_prefix = opts["lab_prefix"] or self._prompt("Lab item-ID prefix (e.g. AGB)", noinput)
        password = opts["password"]
        if not password and not noinput:
            password = getpass.getpass("Admin password: ")
        if not all([email, lab_name, lab_prefix, password]):
            raise CommandError("email, password, lab-name and lab-prefix are all required")

        with transaction.atomic():
            user, created = User.objects.get_or_create(email=email, defaults={"username": email})
            if created:
                user.is_staff = True
                user.is_superuser = True
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Created superuser {email}"))
            else:
                self.stdout.write(f"Reusing existing user {email}")

            slug = slugify(lab_name)
            lab = Lab.objects.filter(slug=slug).first()
            if lab is None:
                lab = create_lab(name=lab_name, item_id_prefix=lab_prefix, slug=slug)
                self.stdout.write(
                    self.style.SUCCESS(f"Created lab '{lab.name}' ({lab.item_id_prefix})")
                )
            else:
                self.stdout.write(f"Reusing existing lab '{lab.name}'")

            add_member(user=user, lab=lab, role_names=["Lab manager"])

        self.stdout.write(self.style.SUCCESS("Bootstrap complete."))

    def _prompt(self, label: str, noinput: bool) -> str:
        if noinput:
            return ""
        return input(f"{label}: ").strip()
