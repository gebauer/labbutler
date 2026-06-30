from django.urls import path

from . import views

app_name = "imports"

urlpatterns = [
    path("", views.start, name="start"),
    path("map/", views.mapping, name="mapping"),
    path("preview/", views.preview, name="preview"),
    path("cancel/", views.cancel, name="cancel"),
]
