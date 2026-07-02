import pytest
from django.contrib.auth import get_user_model

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
