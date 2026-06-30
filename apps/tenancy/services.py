"""Tenancy operations that span multiple models (kept out of views/commands)."""

from django.db import transaction
from django.utils.text import slugify

from .models import Lab, Membership, Role, User


@transaction.atomic
def create_lab(*, name: str, item_id_prefix: str, slug: str | None = None) -> Lab:
    """Create a lab and clone the template roles into editable, lab-owned roles.

    No installation-wide role ever governs behaviour, so every new lab gets its own
    copy of the starter roles (permissions included) that it is then free to edit.
    """
    lab = Lab.objects.create(
        name=name,
        slug=slug or slugify(name),
        item_id_prefix=item_id_prefix.upper(),
    )
    for template in Role.objects.filter(is_template=True, lab__isnull=True):
        cloned = Role.objects.create(lab=lab, name=template.name, is_template=False)
        cloned.permissions.set(template.permissions.all())
    return lab


@transaction.atomic
def add_member(*, user: User, lab: Lab, role_names: list[str] | None = None) -> Membership:
    """Add ``user`` to ``lab`` with the named lab-owned roles (by default: none)."""
    membership, _ = Membership.objects.get_or_create(user=user, lab=lab)
    if role_names:
        membership.roles.set(Role.objects.filter(lab=lab, name__in=role_names))
    return membership
