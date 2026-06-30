from django.db import migrations

from apps.tenancy.catalog import (
    ALL_PERMISSION_CODES,
    PERMISSION_CATALOG,
    TEMPLATE_ROLES,
)


def seed(apps, schema_editor):
    Permission = apps.get_model("tenancy", "Permission")
    Role = apps.get_model("tenancy", "Role")

    for code, label in PERMISSION_CATALOG:
        Permission.objects.update_or_create(code=code, defaults={"label": label})

    for name, codes in TEMPLATE_ROLES.items():
        role, _ = Role.objects.update_or_create(
            lab=None, name=name, defaults={"is_template": True}
        )
        wanted = ALL_PERMISSION_CODES if codes == ["*"] else codes
        role.permissions.set(Permission.objects.filter(code__in=wanted))


def unseed(apps, schema_editor):
    Permission = apps.get_model("tenancy", "Permission")
    Role = apps.get_model("tenancy", "Role")
    Role.objects.filter(is_template=True, lab__isnull=True).delete()
    Permission.objects.filter(code__in=ALL_PERMISSION_CODES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0002_lab_permission_role_membership_and_more"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
