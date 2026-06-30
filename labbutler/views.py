from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def home(request: HttpRequest) -> HttpResponse:
    """Placeholder landing page until the inventory dashboard lands."""
    return render(request, "home.html")
