"""Tests for the human-ID helpers (suggestions and manual-entry normalisation)."""

import pytest

from apps.inventory import ids
from apps.inventory.models import Item
from apps.tenancy.services import create_lab


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


@pytest.mark.django_db
def test_suggest_ids_starts_after_highest_used(lab):
    Item.objects.create(lab=lab, human_id="AGB-00001", name="a")
    Item.objects.create(lab=lab, human_id="AGB-00003", name="c")  # gap at 2
    # Suggestions come after the highest used number (gaps are left for manual entry).
    assert ids.suggest_ids(lab, 3) == ["AGB-00004", "AGB-00005", "AGB-00006"]


@pytest.mark.django_db
def test_suggest_ids_ignores_legacy_serials(lab):
    Item.objects.create(lab=lab, human_id="ch-0005", name="legacy")  # not {PREFIX}-…
    assert ids.suggest_ids(lab, 1) == ["AGB-00001"]


@pytest.mark.django_db
def test_normalize_item_id(lab):
    assert ids.normalize_item_id(lab, "agb-42") == "AGB-00042"
    assert ids.normalize_item_id(lab, "AGB-00042") == "AGB-00042"
    assert ids.normalize_item_id(lab, "AGB42") == "AGB-00042"
    for bad in ("XYZ-1", "", "AGB-"):
        with pytest.raises(ValueError):
            ids.normalize_item_id(lab, bad)


@pytest.mark.django_db
def test_item_id_taken(lab):
    Item.objects.create(lab=lab, human_id="AGB-00001", name="a")
    assert ids.item_id_taken(lab, "AGB-00001") is True
    assert ids.item_id_taken(lab, "AGB-00002") is False
