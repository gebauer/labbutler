from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("", views.home, name="home"),
]
