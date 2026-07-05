from django.urls import path

from . import views

app_name = "tenancy"

urlpatterns = [
    path("welcome/", views.onboarding, name="onboarding"),
    path("settings/", views.account_settings, name="settings"),
    path("impersonate/", views.impersonate, name="impersonate"),
    path("impersonate/stop/", views.stop_impersonating, name="stop_impersonating"),
]
