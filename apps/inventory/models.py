from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.tenancy.models import Lab
from labbutler.abstract import TimeStampedModel


class Location(TimeStampedModel):
    """Hierarchical storage location (room -> fridge/freezer -> tray), any depth.

    Hierarchy helpers (`tree_for_lab`, `subtree_pks`, `attach_path_names`) work off a
    single query for the lab's locations, so callers never walk parent links row by row.
    """

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
        return self.full_path

    @property
    def full_path(self) -> str:
        """The root→leaf name chain, e.g. ``Room 376 / Fridge A / Shelf 2``."""
        return " / ".join(self.path_names())

    def path_names(self) -> list[str]:
        """Ancestor names root→self. Uses names cached by a bulk helper when present;
        otherwise walks parent links (cycle-safe, one query per level)."""
        cached = getattr(self, "_path_names", None)
        if cached is not None:
            return cached
        names: list[str] = []
        node: Location | None = self
        seen: set[int] = set()
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            names.append(node.name)
            node = node.parent
        names.reverse()
        self._path_names = names
        return names

    @classmethod
    def _by_parent(cls, lab: Lab) -> dict[int | None, list["Location"]]:
        """The lab's locations grouped by parent pk, children name-sorted."""
        children: dict[int | None, list[Location]] = {}
        for location in cls.objects.filter(lab=lab).order_by("name"):
            children.setdefault(location.parent_id, []).append(location)
        return children

    @classmethod
    def tree_for_lab(cls, lab: Lab) -> list["Location"]:
        """All lab locations in depth-first order, each with ``depth`` and cached path
        names set — the canonical source for dropdowns and tree listings."""
        children = cls._by_parent(lab)
        ordered: list[Location] = []

        def walk(parent_id: int | None, prefix: list[str], depth: int) -> None:
            for node in children.get(parent_id, []):
                node.depth = depth
                node._path_names = [*prefix, node.name]
                ordered.append(node)
                walk(node.pk, node._path_names, depth + 1)

        walk(None, [], 0)
        # Orphans under a cycle (bad data) would be silently dropped by the walk;
        # append them flat so nothing becomes uneditable.
        if len(ordered) < sum(len(nodes) for nodes in children.values()):
            listed = {node.pk for node in ordered}
            for nodes in children.values():
                for node in nodes:
                    if node.pk not in listed:
                        node.depth = 0
                        ordered.append(node)
        return ordered

    @classmethod
    def subtree_pks(cls, lab: Lab, root_pk: int) -> list[int]:
        """The pk of ``root_pk`` plus all its descendants (for whole-room filtering)."""
        children = cls._by_parent(lab)
        pks: list[int] = []
        queue = [root_pk]
        while queue:
            pk = queue.pop()
            if pk in pks:
                continue  # cycle guard on bad data
            pks.append(pk)
            queue.extend(node.pk for node in children.get(pk, []))
        return pks

    @classmethod
    def attach_path_names(cls, lab: Lab, locations: list["Location"]) -> None:
        """Cache path names on the given instances from one query (for list pages)."""
        parents: dict[int, tuple[int | None, str]] = {
            pk: (parent_id, name)
            for pk, parent_id, name in cls.objects.filter(lab=lab).values_list(
                "pk", "parent_id", "name"
            )
        }
        for location in locations:
            names: list[str] = []
            pk: int | None = location.pk
            seen: set[int] = set()
            while pk is not None and pk in parents and pk not in seen:
                seen.add(pk)
                parent_id, name = parents[pk]
                names.append(name)
                pk = parent_id
            names.reverse()
            location._path_names = names


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
