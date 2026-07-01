"""A single, generic comment model usable on any object (items, requests, …).

Comments hang off their target via Django's content types, so one model serves every
commentable thing. They are lab-scoped for tenancy and keep the author for display.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.tenancy.models import Lab
from labbutler.abstract import TimeStampedModel


class Comment(TimeStampedModel):
    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="comments",
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    body = models.TextField()

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"comment by {self.author_id} on {self.content_type_id}#{self.object_id}"

    @classmethod
    def for_object(cls, obj) -> models.QuerySet:
        """Comments on ``obj``, oldest first, with authors preloaded."""
        content_type = ContentType.objects.get_for_model(obj.__class__)
        return cls.objects.filter(content_type=content_type, object_id=obj.pk).select_related(
            "author"
        )
