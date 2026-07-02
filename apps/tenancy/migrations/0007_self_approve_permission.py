from django.db import migrations

from apps.tenancy.catalog import PERMISSION_CATALOG

_CODE = "self_approve"
_ROLE = "Member"


def add_permission(apps, schema_editor):
    """Seed the self-approve permission and grant it to every Member role."""
    Permission = apps.get_model("tenancy", "Permission")
    Role = apps.get_model("tenancy", "Role")

    label = dict(PERMISSION_CATALOG)[_CODE]
    perm, _ = Permission.objects.update_or_create(code=_CODE, defaults={"label": label})
    # Both the template and every existing lab's cloned "Member" role.
    for role in Role.objects.filter(name=_ROLE):
        role.permissions.add(perm)


def remove_permission(apps, schema_editor):
    Permission = apps.get_model("tenancy", "Permission")
    Permission.objects.filter(code=_CODE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0006_membership_approval_notifications_and_more"),
    ]

    operations = [
        migrations.RunPython(add_permission, remove_permission),
    ]
