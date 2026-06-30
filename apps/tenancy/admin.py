from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Lab, Membership, Permission, Role, User


@admin.register(User)
class LabButlerUserAdmin(UserAdmin):
    list_display = ("email", "username", "is_staff", "is_superuser")
    ordering = ("email",)


@admin.register(Lab)
class LabAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "item_id_prefix", "next_item_number")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "lab", "is_template")
    list_filter = ("is_template", "lab")
    filter_horizontal = ("permissions",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "lab", "joined_at")
    list_filter = ("lab",)
    filter_horizontal = ("roles",)


admin.site.register(Permission)
