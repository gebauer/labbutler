from django.urls import path

from . import views

app_name = "tenancy"

urlpatterns = [
    path("welcome/", views.onboarding, name="onboarding"),
    path("settings/", views.account_settings, name="settings"),
    path("impersonate/", views.impersonate, name="impersonate"),
    path("impersonate/stop/", views.stop_impersonating, name="stop_impersonating"),
    # Public: the confirm route first, so "confirm" is never read as a join token.
    path("join/confirm/<str:token>/", views.join_confirm, name="join_confirm"),
    path("join/<str:token>/", views.join_request, name="join_request"),
]
