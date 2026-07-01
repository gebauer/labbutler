from django.urls import path

from . import manage_views as views

app_name = "manage"

urlpatterns = [
    path("", views.index, name="index"),
    path("settings/", views.settings, name="settings"),
    path("<slug:kind>/", views.crud_list, name="list"),
    path("<slug:kind>/add/", views.crud_form, name="add"),
    path("<slug:kind>/<int:pk>/edit/", views.crud_form, name="edit"),
    path("<slug:kind>/<int:pk>/delete/", views.crud_delete, name="delete"),
]
