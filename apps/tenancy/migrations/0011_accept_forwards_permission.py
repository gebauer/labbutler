from django.db import migrations

from apps.tenancy.catalog import PERMISSION_CATALOG

_CODE = "accept_forwards"


def add_permission(apps, schema_editor):
    """Seed accept_forwards and grant it to every role that can place orders.

    The forward-to list used to be "everyone with place_order"; granting the new
    permission to exactly those roles keeps existing labs' forward lists unchanged
    until they choose to narrow them.
    """
    Permission = apps.get_model("tenancy", "Permission")
    Role = apps.get_model("tenancy", "Role")

    label = dict(PERMISSION_CATALOG)[_CODE]
    perm, _ = Permission.objects.update_or_create(code=_CODE, defaults={"label": label})
    for role in Role.objects.filter(permissions__code="place_order").distinct():
        role.permissions.add(perm)


def remove_permission(apps, schema_editor):
    Permission = apps.get_model("tenancy", "Permission")
    Permission.objects.filter(code=_CODE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0010_lab_default_currency"),
    ]

    operations = [
        migrations.RunPython(add_permission, remove_permission),
    ]
