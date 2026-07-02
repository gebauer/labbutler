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
    path("<int:pk>/<str:action>/", views.request_action, name="request_action"),
]
