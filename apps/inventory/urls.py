from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.item_list, name="item_list"),
    path("new/", views.item_create, name="item_create"),
    path("<int:pk>/", views.item_detail, name="item_detail"),
    path("<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("switch-lab/<slug:slug>/", views.switch_lab, name="switch_lab"),
]
