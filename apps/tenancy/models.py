from decimal import Decimal

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models, transaction

from labbutler.abstract import TimeStampedModel


class LabButlerUserManager(UserManager):
    """User manager that treats email as the login identifier."""

    def _create_user(self, username, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        # Keep username populated (Django internals expect it) but mirror the email.
        username = username or email
        return super()._create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    """Custom user: email is the canonical identifier.

    A surrogate username is retained for Django admin/internal compatibility but the
    application authenticates and displays users by email.
    """

    email = models.EmailField("email address", unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = LabButlerUserManager()

    def __str__(self) -> str:
        return self.email or self.username

    def can(self, lab: "Lab", permission_code: str) -> bool:
        """Return whether this user holds ``permission_code`` in ``lab``.

        Effective rights = the union of permissions across all roles on the user's
        membership of that lab. A single resolution point so views/templates never
        reach into roles directly.
        """
        if self.is_superuser:
            return True
        return Permission.objects.filter(
            roles__memberships__user=self,
            roles__memberships__lab=lab,
            code=permission_code,
        ).exists()


class Lab(TimeStampedModel):
    """Top-level tenant and scoping anchor. A single-lab deployment is one row."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    # Frozen prefix for newly-created item human IDs, e.g. "AGB" -> "AGB-04821".
    item_id_prefix = models.CharField(max_length=16)
    # Monotonic counter backing human-ID allocation; never decremented.
    next_item_number = models.PositiveIntegerField(default=1)
    default_vat_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.19"))

    def __str__(self) -> str:
        return self.name

    def allocate_item_id(self) -> str:
        """Atomically reserve and format the next human ID for a new item.

        Locks the lab row so concurrent check-ins/imports cannot collide. The returned
        identifier is frozen on the item forever and never recomputed from any field.
        """
        with transaction.atomic():
            lab = Lab.objects.select_for_update().get(pk=self.pk)
            number = lab.next_item_number
            lab.next_item_number = number + 1
            lab.save(update_fields=["next_item_number", "updated_at"])
        self.next_item_number = number + 1
        return f"{self.item_id_prefix}-{number:05d}"


class Permission(models.Model):
    """Fixed, installation-wide catalog of capabilities (not per-lab)."""

    code = models.CharField(max_length=64, primary_key=True)
    label = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.code


class Role(TimeStampedModel):
    """A named bundle of permissions.

    Roles are per-lab (each lab invents its own). Template roles ship as starter sets
    (``is_template=True``, no lab) and are cloned into editable, lab-owned roles at lab
    creation; no installation-wide role ever governs behaviour.
    """

    lab = models.ForeignKey(
        Lab, on_delete=models.CASCADE, related_name="roles", null=True, blank=True
    )
    name = models.CharField(max_length=100)
    is_template = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lab", "name"], name="unique_role_name_per_lab"),
        ]

    def __str__(self) -> str:
        scope = "template" if self.is_template else (self.lab and self.lab.slug)
        return f"{self.name} ({scope})"


class Membership(TimeStampedModel):
    """A user's participation in one lab, carrying that lab's roles."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="memberships")
    roles = models.ManyToManyField(Role, related_name="memberships", blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "lab"], name="unique_membership_per_user_lab"),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.lab}"
