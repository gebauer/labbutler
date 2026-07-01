from django.db import migrations

from apps.inventory.ghs import STATEMENTS_EN, canonical_code, kind_for


def seed(apps, schema_editor):
    """Seed the GHS catalog and normalise any existing (e.g. upper-cased) codes.

    Earlier imports stored codes verbatim and blank text (``H350I`` with no wording).
    We seed the canonical catalog, then merge each legacy row into its canonical code —
    moving item links across — so every hazard resolves to one shared, correctly-cased
    statement with English text.
    """
    HazardStatement = apps.get_model("inventory", "HazardStatement")

    for code, text_en in STATEMENTS_EN.items():
        HazardStatement.objects.update_or_create(
            code=code, defaults={"kind": kind_for(code), "text_en": text_en}
        )

    for legacy in list(HazardStatement.objects.all()):
        canonical = canonical_code(legacy.code)
        if canonical == legacy.code:
            continue
        target, _ = HazardStatement.objects.get_or_create(
            code=canonical,
            defaults={"kind": kind_for(canonical), "text_en": STATEMENTS_EN.get(canonical, "")},
        )
        for item in legacy.items.all():
            item.hazards.add(target)
            item.hazards.remove(legacy)
        legacy.delete()


def unseed(apps, schema_editor):
    """Clear the seeded text (rows and any merges are left in place)."""
    HazardStatement = apps.get_model("inventory", "HazardStatement")
    HazardStatement.objects.filter(code__in=STATEMENTS_EN).update(text_en="")


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
