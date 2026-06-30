from django.conf import settings
from django.db import models


class AuditEntry(models.Model):
    """Append-only, immutable record of a single transaction.

    Written once and never edited or deleted in application code. Captures request
    state changes, check-in/out, approvals, role/member/budget/supplier edits, imports.
    Use :meth:`record` to write entries; saving an existing entry is refused.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_entries",
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    lab = models.ForeignKey(
        "tenancy.Lab", on_delete=models.CASCADE, related_name="audit_entries"
    )
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64, blank=True)
    changes = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name_plural = "audit entries"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["lab", "-timestamp"]),
            models.Index(fields=["target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}#{self.target_id}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            # Immutability is enforced in app code: entries are write-once.
            raise ValueError("AuditEntry is append-only and cannot be modified")
        super().save(*args, **kwargs)

    @classmethod
    def record(cls, *, lab, action, target, actor=None, changes=None) -> "AuditEntry":
        """Append an audit entry for ``target`` (any model instance or (type, id))."""
        if isinstance(target, tuple):
            target_type, target_id = target
        else:
            target_type = target.__class__.__name__
            target_id = str(target.pk)
        return cls.objects.create(
            lab=lab,
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            changes=changes or {},
        )
