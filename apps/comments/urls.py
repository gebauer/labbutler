from django.urls import path

from . import views

app_name = "comments"

urlpatterns = [
    path("<str:model>/<int:pk>/add/", views.add_comment, name="add"),
]
