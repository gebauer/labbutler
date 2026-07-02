from django.urls import path

from . import views

app_name = "tenancy"

urlpatterns = [
    path("settings/notifications/", views.notification_settings, name="notification_settings"),
    path("impersonate/", views.impersonate, name="impersonate"),
    path("impersonate/stop/", views.stop_impersonating, name="stop_impersonating"),
]
