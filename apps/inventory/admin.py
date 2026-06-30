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


admin.site.register(Tag)
admin.site.register(FieldDefinition)
admin.site.register(FieldPreset)
