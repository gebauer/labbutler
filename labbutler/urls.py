from django.contrib import admin
from django.urls import include, path

from apps.tenancy.views import FirstLoginView

from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Overrides the login view from the auth include below (same URL, so reversing
    # "login" is unaffected) to send first-time users to the welcome tour.
    path("accounts/login/", FirstLoginView.as_view(), name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("imports/", include("apps.imports.urls")),
    path("requests/", include("apps.procurement.urls")),
    path("comments/", include("apps.comments.urls")),
    path("attachments/", include("apps.attachments.urls")),
    path("manage/", include("apps.tenancy.manage_urls")),
    path("", include("apps.tenancy.urls")),
    path("healthz", views.healthz, name="healthz"),
    path("privacy/", views.privacy, name="privacy"),
    path("", views.home, name="home"),
]
