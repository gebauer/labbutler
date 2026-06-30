"""Shared abstract base models (no tables of their own)."""

from django.db import models


class TimeStampedModel(models.Model):
    """Adds created/updated timestamps to a model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
