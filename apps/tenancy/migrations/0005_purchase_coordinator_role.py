from django.db import migrations

_NAME = "Purchase coordinator"
_PERMS = ["view_requests", "place_order"]


def add_role(apps, schema_editor):
    """Add the template role and clone it into every existing lab."""
    Role = apps.get_model("tenancy", "Role")
    Permission = apps.get_model("tenancy", "Permission")
    Lab = apps.get_model("tenancy", "Lab")
    perms = list(Permission.objects.filter(code__in=_PERMS))

    template, _ = Role.objects.get_or_create(
        lab=None, name=_NAME, defaults={"is_template": True}
    )
    template.permissions.set(perms)

    for lab in Lab.objects.all():
        role, created = Role.objects.get_or_create(
            lab=lab, name=_NAME, defaults={"is_template": False}
        )
        if created:
            role.permissions.set(perms)


def remove_role(apps, schema_editor):
    Role = apps.get_model("tenancy", "Role")
    Role.objects.filter(name=_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0004_alter_lab_default_vat_rate"),
    ]

    operations = [
        migrations.RunPython(add_role, remove_role),
    ]
