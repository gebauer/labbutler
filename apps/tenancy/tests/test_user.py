import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
def test_create_user_uses_email_as_identifier():
    user = User.objects.create_user(
        username="", email="Alice@Uni-Koeln.de", password="pw"
    )
    # Email is normalised (domain lowercased) and used as the login field.
    assert user.email == "Alice@uni-koeln.de"
    assert User.USERNAME_FIELD == "email"
    assert str(user) == "Alice@uni-koeln.de"


@pytest.mark.django_db
def test_create_user_requires_email():
    with pytest.raises(ValueError):
        User.objects.create_user(username="bob", email="", password="pw")
