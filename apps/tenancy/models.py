from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


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
