from django.contrib import admin

from .models import (
    FieldDefinition,
    FieldPreset,
    HazardStatement,
    Item,
    Location,
    Tag,
)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("human_id", "name", "lab", "location", "owner", "expiration_date")
    list_filter = ("lab", "signal_word", "storage_class")
    search_fields = ("human_id", "legacy_serial", "name", "barcode", "cas_number")
    filter_horizontal = ("tags", "hazards")
    readonly_fields = ("human_id",)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "lab", "room_number")
    list_filter = ("lab",)


@admin.register(HazardStatement)
class HazardStatementAdmin(admin.ModelAdmin):
    list_display = ("code", "kind", "category")
    list_filter = ("kind",)
    search_fields = ("code", "text_en", "text_de")


@admin.register(FieldDefinition)
class FieldDefinitionAdmin(admin.ModelAdmin):
    list_display = ("label", "key", "data_type", "lab")
    list_filter = ("lab", "data_type")
    search_fields = ("label", "key")


@admin.register(FieldPreset)
class FieldPresetAdmin(admin.ModelAdmin):
    list_display = ("name", "lab")
    list_filter = ("lab",)
    # fields__* so a preset can be found by any field it bundles.
    search_fields = ("name", "fields__label", "fields__key")
    filter_horizontal = ("fields",)


admin.site.register(Tag)
