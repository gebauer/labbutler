from django.urls import path

from . import views

app_name = "procurement"

urlpatterns = [
    path("", views.request_list, name="request_list"),
    path("new/", views.request_create, name="request_create"),
    path("<int:pk>/", views.request_detail, name="request_detail"),
    path("<int:pk>/edit/", views.request_edit, name="request_edit"),
    path("<int:pk>/receive/", views.request_receive, name="request_receive"),
    path("<int:pk>/forward/", views.request_forward, name="request_forward"),
    path("<int:pk>/self-approve/", views.request_self_approve, name="request_self_approve"),
    path("<int:pk>/po/upload/", views.request_po_upload, name="request_po_upload"),
    path(
        "<int:pk>/po/upload-signed/",
        views.request_po_upload_signed,
        name="request_po_upload_signed",
    ),
    path(
        "<int:pk>/po/<int:po_pk>/<str:kind>/",
        views.request_po_download,
        name="request_po_download",
    ),
    path("<int:pk>/reroute/", views.request_reroute, name="request_reroute"),
    path(
        "<int:pk>/resend-zk-email/", views.request_resend_zk_email, name="request_resend_zk_email"
    ),
    path("<int:pk>/<str:action>/", views.request_action, name="request_action"),
]
