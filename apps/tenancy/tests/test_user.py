import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

User = get_user_model()


@pytest.mark.django_db
def test_create_user_uses_email_as_identifier():
    user = User.objects.create_user(username="", email="Alice@Uni-Koeln.de", password="pw")
    # Email is normalised (domain lowercased) and used as the login field.
    assert user.email == "Alice@uni-koeln.de"
    assert User.USERNAME_FIELD == "email"
    assert str(user) == "Alice@uni-koeln.de"


@pytest.mark.django_db
def test_create_user_requires_email():
    with pytest.raises(ValueError):
        User.objects.create_user(username="bob", email="", password="pw")


@pytest.mark.django_db
def test_email_uniqueness_is_case_insensitive():
    User.objects.create_user(username="", email="Alice@x.de", password="pw")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(username="", email="alice@x.de", password="pw")


@pytest.mark.django_db
def test_get_by_natural_key_matches_case_insensitively():
    user = User.objects.create_user(username="", email="Alice@x.de", password="pw")
    assert User.objects.get_by_natural_key("ALICE@x.de") == user


@pytest.mark.django_db
def test_get_or_create_by_email_reuses_existing_regardless_of_case():
    user = User.objects.create_user(username="", email="Alice@x.de", password="pw")
    found, created = User.objects.get_or_create_by_email("alice@X.de", defaults={"username": "x"})
    assert found == user and created is False
    # The stored casing is preserved; no duplicate is spawned.
    assert found.email == "Alice@x.de"
    assert User.objects.filter(email__iexact="alice@x.de").count() == 1


@pytest.mark.django_db
def test_get_or_create_by_email_creates_with_typed_casing():
    user, created = User.objects.get_or_create_by_email(
        "Bob@x.de", defaults={"username": "Bob@x.de"}
    )
    assert created is True
    assert user.email == "Bob@x.de"


@pytest.mark.django_db
def test_display_name_falls_back_to_email_when_no_friendly_name():
    user = User.objects.create_user(username="", email="bob@x.de", password="pw")
    assert user.display_name == "bob@x.de"
    assert str(user) == "bob@x.de"


@pytest.mark.django_db
def test_display_name_uses_friendly_name_when_set():
    user = User.objects.create_user(
        username="", email="bob@x.de", password="pw", friendly_name="Bob Builder"
    )
    assert user.display_name == "Bob Builder"
    assert str(user) == "Bob Builder"
    # Friendly name is display-only; the email identity is untouched.
    assert user.email == "bob@x.de"
