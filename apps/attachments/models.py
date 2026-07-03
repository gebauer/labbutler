"""A single, generic attachment model usable on any object (items, requests, …).

Like comments, attachments hang off their target via Django's content types and are
lab-scoped for tenancy. Files land under a random, per-lab storage path — the original
filename is kept as metadata only, so uploads can never influence the path on disk.
Files are not web-served directly; downloads go through a permission-checked view.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import models

from apps.tenancy.models import Lab
from labbutler.abstract import TimeStampedModel


def attachment_upload_path(instance: Attachment, filename: str) -> str:
    """Random storage name (original extension only) inside the owning lab's folder."""
    suffix = Path(filename).suffix.lower()
    return f"attachments/lab_{instance.lab_id}/{uuid.uuid4().hex}{suffix}"


class Attachment(TimeStampedModel):
    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="attachments",
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")

    file = models.FileField(upload_to=attachment_upload_path)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.original_name} on {self.content_type_id}#{self.object_id}"

    @classmethod
    def for_object(cls, obj) -> models.QuerySet:
        """Attachments on ``obj``, oldest first, with uploaders preloaded."""
        content_type = ContentType.objects.get_for_model(obj.__class__)
        return cls.objects.filter(content_type=content_type, object_id=obj.pk).select_related(
            "uploaded_by"
        )

    def copy_to(self, target) -> Attachment:
        """Duplicate this attachment onto another object (e.g. request → checked-in item).

        The file bytes are copied to a fresh storage path so the two rows have fully
        independent lifecycles — deleting one never breaks the other.
        """
        with self.file.open("rb") as source:
            content = ContentFile(source.read(), name=self.original_name)
        return Attachment.objects.create(
            lab=self.lab,
            uploaded_by=self.uploaded_by,
            target=target,
            file=content,
            original_name=self.original_name,
            size=self.size,
        )

    def delete(self, *args, **kwargs):
        storage, name = self.file.storage, self.file.name
        result = super().delete(*args, **kwargs)
        # Remove the blob only after the row is gone; a stray file is better than a
        # dangling row pointing at nothing.
        if name:
            storage.delete(name)
        return result
