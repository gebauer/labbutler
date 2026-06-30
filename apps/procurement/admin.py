from django.contrib import admin

from .models import Budget, Request, ShippingAddress, Vendor


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ("item_name", "lab", "status", "vendor", "budget", "total", "is_urgent")
    list_filter = ("lab", "status", "is_urgent")
    search_fields = ("item_name", "catalog_number", "po_number", "quote_id")
    readonly_fields = ("tax", "total")


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "lab", "owner")
    list_filter = ("lab",)


admin.site.register(Vendor)
admin.site.register(ShippingAddress)
