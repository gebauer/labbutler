"""Vendor maintenance tests: duplicate detection and merging suppliers."""

import pytest

from apps.audit.models import AuditEntry
from apps.inventory.models import Item
from apps.procurement.models import Request, Vendor
from apps.procurement.services import find_duplicate_vendors, merge_vendors
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab


@pytest.fixture
def lab(db):
    return create_lab(name="Merge Lab", item_id_prefix="ML")


@pytest.fixture
def manager(lab):
    user = User.objects.create_user(username="", email="boss@x.de", password="pw")
    add_member(user=user, lab=lab, role_names=["Lab manager"])
    return user


def _vendor(lab, name: str) -> Vendor:
    return Vendor.objects.create(lab=lab, name=name)


# --- find_duplicate_vendors ---------------------------------------------------------


@pytest.mark.django_db
def test_duplicates_group_case_whitespace_and_near_matches(lab):
    a = _vendor(lab, "Sigma Aldrich")
    b = _vendor(lab, "sigma  aldrich ")
    c = _vendor(lab, "Sigma-Aldrich")
    _vendor(lab, "Carl Roth")

    groups = find_duplicate_vendors(lab)
    assert len(groups) == 1
    assert set(groups[0]) == {a, b, c}


@pytest.mark.django_db
def test_duplicates_ignore_distinct_names_and_other_labs(lab):
    _vendor(lab, "Carl Roth")
    other = create_lab(name="Other", item_id_prefix="OT")
    _vendor(other, "Carl Roth")  # same name, different lab — not a duplicate here

    assert find_duplicate_vendors(lab) == []


# --- merge_vendors ------------------------------------------------------------------


@pytest.mark.django_db
def test_merge_repoints_requests_and_items_and_deletes_losers(lab, manager):
    winner = _vendor(lab, "Sigma Aldrich")
    loser = _vendor(lab, "sigma aldrich")
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=manager, vendor=loser)
    item = Item.objects.create(lab=lab, human_id="ML-1", name="Tips", vendor=loser)

    merge_vendors(lab=lab, winner=winner, losers=[loser], actor=manager)

    req.refresh_from_db()
    item.refresh_from_db()
    assert req.vendor == winner
    assert item.vendor == winner
    assert not Vendor.objects.filter(pk=loser.pk).exists()


@pytest.mark.django_db
def test_merge_can_rename_winner_even_to_a_losers_name(lab, manager):
    winner = _vendor(lab, "sigma aldrich")
    loser = _vendor(lab, "Sigma-Aldrich GmbH")

    merge_vendors(
        lab=lab, winner=winner, losers=[loser], actor=manager, new_name="Sigma-Aldrich GmbH"
    )

    winner.refresh_from_db()
    assert winner.name == "Sigma-Aldrich GmbH"
    assert Vendor.objects.filter(lab=lab).count() == 1


@pytest.mark.django_db
def test_merge_writes_audit_entry_with_per_loser_counts(lab, manager):
    winner = _vendor(lab, "Sigma")
    loser = _vendor(lab, "sigma ")
    Request.objects.create(lab=lab, item_name="Tips", requested_by=manager, vendor=loser)
    Request.objects.create(lab=lab, item_name="Tubes", requested_by=manager, vendor=loser)
    Item.objects.create(lab=lab, human_id="ML-1", name="Tips", vendor=loser)

    merge_vendors(lab=lab, winner=winner, losers=[loser], actor=manager)

    entry = AuditEntry.objects.get(lab=lab, action="lab.suppliers_merged")
    assert entry.actor == manager
    assert entry.changes["winner"] == "Sigma"
    assert entry.changes["losers"] == [
        {"id": loser.pk, "name": "sigma ", "requests": 2, "items": 1}
    ]
    assert entry.changes["moved_requests"] == 2
    assert entry.changes["moved_items"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bad",
    ["cross_lab_loser", "winner_in_losers", "empty_losers", "name_clash"],
)
def test_merge_rejects_invalid_selection_and_changes_nothing(lab, manager, bad):
    winner = _vendor(lab, "Sigma")
    loser = _vendor(lab, "sigma ")
    _vendor(lab, "Carl Roth")  # unrelated survivor for the name-clash case
    req = Request.objects.create(lab=lab, item_name="Tips", requested_by=manager, vendor=loser)

    kwargs = {"lab": lab, "winner": winner, "losers": [loser], "actor": manager}
    if bad == "cross_lab_loser":
        other = create_lab(name="Other", item_id_prefix="OT")
        kwargs["losers"] = [_vendor(other, "Foreign")]
    elif bad == "winner_in_losers":
        kwargs["losers"] = [winner, loser]
    elif bad == "empty_losers":
        kwargs["losers"] = []
    elif bad == "name_clash":
        kwargs["new_name"] = "carl roth"

    with pytest.raises(ValueError):
        merge_vendors(**kwargs)

    req.refresh_from_db()
    assert req.vendor == loser
    assert Vendor.objects.filter(pk=loser.pk).exists()
    assert not AuditEntry.objects.filter(lab=lab, action="lab.suppliers_merged").exists()


# --- get_or_create_normalized -------------------------------------------------------


@pytest.mark.django_db
def test_get_or_create_normalized_reuses_variants(lab):
    existing = _vendor(lab, "Sigma")
    assert Vendor.objects.get_or_create_normalized(lab=lab, name="  SIGMA ") == existing
    assert Vendor.objects.get_or_create_normalized(lab=lab, name="sigma") == existing
    assert Vendor.objects.filter(lab=lab).count() == 1


@pytest.mark.django_db
def test_get_or_create_normalized_creates_with_collapsed_whitespace(lab):
    vendor = Vendor.objects.get_or_create_normalized(lab=lab, name="  Carl   Roth ")
    assert vendor.name == "Carl Roth"


@pytest.mark.django_db
def test_get_or_create_normalized_is_lab_scoped(lab):
    other = create_lab(name="Other", item_id_prefix="OT")
    _vendor(other, "Sigma")
    vendor = Vendor.objects.get_or_create_normalized(lab=lab, name="Sigma")
    assert vendor.lab == lab
    assert Vendor.objects.filter(name="Sigma").count() == 2
