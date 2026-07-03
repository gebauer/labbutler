from django.urls import path

from . import views

app_name = "attachments"

urlpatterns = [
    path("<str:model>/<int:pk>/add/", views.add_attachment, name="add"),
    path("<int:pk>/download/", views.download_attachment, name="download"),
    path("<int:pk>/delete/", views.delete_attachment, name="delete"),
]
