from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.tenancy.models import Lab
from labbutler.abstract import TimeStampedModel


class Location(TimeStampedModel):
    """Hierarchical storage location (room -> fridge/freezer -> tray)."""

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="locations")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, related_name="children", null=True, blank=True
    )
    name = models.CharField(max_length=200)
    # Optional room number parsed from "Storage room (376)" during import.
    room_number = models.CharField(max_length=20, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lab", "parent", "name"], name="unique_location_per_parent"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Tag(TimeStampedModel):
    """Free-form, multi-membership classification label (e.g. 'antibody', '2022')."""

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lab", "name"], name="unique_tag_per_lab"),
        ]

    def __str__(self) -> str:
        return self.name


class FieldDefinition(TimeStampedModel):
    """A lab-level custom field usable by any item; values live in Item.custom_fields."""

    class DataType(models.TextChoices):
        TEXT = "text", "Text"
        NUMBER = "number", "Number"
        DATE = "date", "Date"
        BOOLEAN = "boolean", "Boolean"

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="field_definitions")
    key = models.CharField(max_length=64)
    label = models.CharField(max_length=200)
    data_type = models.CharField(max_length=16, choices=DataType.choices, default=DataType.TEXT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lab", "key"], name="unique_field_key_per_lab"),
        ]

    def __str__(self) -> str:
        return self.label


class FieldPreset(TimeStampedModel):
    """A named bundle of field definitions ('Chemical fields') — pure convenience.

    Applying a preset just adds its fields to an item; it is never stored as identity
    or classification.
    """

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="field_presets")
    name = models.CharField(max_length=100)
    fields = models.ManyToManyField(FieldDefinition, related_name="presets", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lab", "name"], name="unique_preset_per_lab"),
        ]

    def __str__(self) -> str:
        return self.name


class HazardStatement(models.Model):
    """Global, structured GHS hazard catalog shared installation-wide (not per-lab)."""

    class Kind(models.TextChoices):
        H = "H", "Hazard (H)"
        EUH = "EUH", "EU Hazard (EUH)"
        P = "P", "Precautionary (P)"

    code = models.CharField(max_length=16, primary_key=True)
    kind = models.CharField(max_length=4, choices=Kind.choices)
    text_en = models.CharField(max_length=500, blank=True)
    text_de = models.CharField(max_length=500, blank=True)
    category = models.CharField(max_length=100, blank=True)

    def __str__(self) -> str:
        return self.code


class Item(TimeStampedModel):
    """One physical container = one record.

    The human identifier is assigned once at creation and frozen forever; it is never
    recomputed from any mutable field (the hard rule from LabSuit's reclassification bug).
    """

    class SignalWord(models.TextChoices):
        NONE = "", "None"
        WARNING = "warning", "Warning"
        DANGER = "danger", "Danger"

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="items")
    # Frozen human handle ({PREFIX}-NNNNN for new items). Unique per lab.
    human_id = models.CharField(max_length=64)
    # Original LabSuit serial kept on import (searchable, collisions across types OK).
    legacy_serial = models.CharField(max_length=64, blank=True, db_index=True)
    barcode = models.CharField(max_length=128, blank=True)

    name = models.CharField(max_length=500)
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="items"
    )
    vendor = models.ForeignKey(
        "procurement.Vendor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_items",
    )

    price_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_currency = models.CharField(max_length=3, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    lot_number = models.CharField(max_length=128, blank=True)
    catalog_number = models.CharField(max_length=128, blank=True)
    cas_number = models.CharField(max_length=64, blank=True)

    # Structured hazard fields (parsed out of LabSuit's TAGS soup).
    signal_word = models.CharField(
        max_length=10, choices=SignalWord.choices, blank=True, default=""
    )
    wgk = models.CharField("Wassergefährdungsklasse", max_length=10, blank=True)
    storage_class = models.CharField("Lagerklasse (TRGS 510)", max_length=20, blank=True)

    # Flexible per-lab field values (GIN-indexed for search).
    custom_fields = models.JSONField(default=dict, blank=True)

    tags = models.ManyToManyField(Tag, related_name="items", blank=True)
    hazards = models.ManyToManyField(HazardStatement, related_name="items", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lab", "human_id"], name="unique_human_id_per_lab"),
        ]
        indexes = [
            models.Index(fields=["lab", "name"]),
            GinIndex(fields=["custom_fields"], name="item_custom_fields_gin"),
        ]

    def __str__(self) -> str:
        return f"{self.human_id} · {self.name}"
