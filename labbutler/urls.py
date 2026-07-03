from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("imports/", include("apps.imports.urls")),
    path("requests/", include("apps.procurement.urls")),
    path("comments/", include("apps.comments.urls")),
    path("attachments/", include("apps.attachments.urls")),
    path("manage/", include("apps.tenancy.manage_urls")),
    path("", include("apps.tenancy.urls")),
    path("healthz", views.healthz, name="healthz"),
    path("", views.home, name="home"),
]
