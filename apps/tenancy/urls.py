from django.urls import path

from . import views

app_name = "tenancy"

urlpatterns = [
    path("impersonate/", views.impersonate, name="impersonate"),
    path("impersonate/stop/", views.stop_impersonating, name="stop_impersonating"),
]
