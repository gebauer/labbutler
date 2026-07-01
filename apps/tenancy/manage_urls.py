from django.urls import path

from . import manage_views as views

app_name = "manage"

urlpatterns = [
    path("", views.index, name="index"),
    path("settings/", views.settings, name="settings"),
    # Members and roles — must precede the generic <kind> routes below.
    path("members/", views.members, name="members"),
    path("members/add/", views.member_add, name="member_add"),
    path("members/<int:pk>/edit/", views.member_edit, name="member_edit"),
    path("members/<int:pk>/remove/", views.member_remove, name="member_remove"),
    path("roles/", views.role_list, name="roles"),
    path("roles/add/", views.role_form, name="role_add"),
    path("roles/<int:pk>/edit/", views.role_form, name="role_edit"),
    path("roles/<int:pk>/delete/", views.role_delete, name="role_delete"),
    # Generic registry-driven CRUD (suppliers / budgets / addresses / fields).
    path("<slug:kind>/", views.crud_list, name="list"),
    path("<slug:kind>/add/", views.crud_form, name="add"),
    path("<slug:kind>/<int:pk>/edit/", views.crud_form, name="edit"),
    path("<slug:kind>/<int:pk>/delete/", views.crud_delete, name="delete"),
]
