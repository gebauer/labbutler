from django.db import migrations

from apps.tenancy.catalog import PERMISSION_CATALOG

_CODES = ["create_po", "sign_po", "send_po_to_central", "reroute_procurement"]

# Which existing capability marks a role as a sensible default holder of each new one:
# signing authority defaults to lab management; the workflow around the PO (create,
# send, reroute) defaults to whoever already places orders. Labs recompose freely.
_GRANT_ALONGSIDE = {
    "create_po": "place_order",
    "sign_po": "manage_lab",
    "send_po_to_central": "place_order",
    "reroute_procurement": "place_order",
}


def add_permissions(apps, schema_editor):
    Permission = apps.get_model("tenancy", "Permission")
    Role = apps.get_model("tenancy", "Role")

    labels = dict(PERMISSION_CATALOG)
    for code in _CODES:
        perm, _ = Permission.objects.update_or_create(code=code, defaults={"label": labels[code]})
        anchor = _GRANT_ALONGSIDE[code]
        for role in Role.objects.filter(permissions__code=anchor).distinct():
            role.permissions.add(perm)
        # Roles with manage_lab (lab managers) hold the full workflow either way.
        for role in Role.objects.filter(permissions__code="manage_lab").distinct():
            role.permissions.add(perm)


def remove_permissions(apps, schema_editor):
    Permission = apps.get_model("tenancy", "Permission")
    Permission.objects.filter(code__in=_CODES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0014_lab_central_purchasing_threshold_net_and_more"),
    ]

    operations = [
        migrations.RunPython(add_permissions, remove_permissions),
    ]
