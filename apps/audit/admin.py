from django.contrib import admin

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "action", "target_type", "target_id", "actor", "lab")
    list_filter = ("lab", "action", "target_type")
    search_fields = ("target_id", "action")
    readonly_fields = ("timestamp", "actor", "lab", "action", "target_type", "target_id", "changes")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
