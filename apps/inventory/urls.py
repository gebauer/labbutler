from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.item_list, name="item_list"),
    path("new/", views.item_create, name="item_create"),
    path("scan/", views.scan_page, name="scan_page"),
    path("scan/resolve/", views.scan_resolve, name="scan_resolve"),
    path("<int:pk>/", views.item_detail, name="item_detail"),
    path("<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("<int:pk>/label/", views.item_label, name="item_label"),
    path("<int:pk>/label/pdf/", views.item_label_pdf, name="item_label_pdf"),
    path("<int:pk>/label/ghs-pdf/", views.item_ghs_label_pdf, name="item_ghs_label_pdf"),
    path("labels/", views.label_sheet, name="label_sheet"),
    path("ghs-lookup/", views.ghs_lookup, name="ghs_lookup"),
    path("switch-lab/<slug:slug>/", views.switch_lab, name="switch_lab"),
]
