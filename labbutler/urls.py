from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.tenancy.views import FirstLoginView

from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Overrides the login view from the auth include below (same URL, so reversing
    # "login" is unaffected) to send first-time users to the welcome tour.
    path("accounts/login/", FirstLoginView.as_view(), name="login"),
    # Same trick for password reset: adds the HTML alternative to the reset mail.
    path(
        "accounts/password_reset/",
        auth_views.PasswordResetView.as_view(
            html_email_template_name="registration/password_reset_email_html.html"
        ),
        name="password_reset",
    ),
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
