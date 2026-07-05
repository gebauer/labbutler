"""Label-scanner tests: code resolution, ScanEvent logging, and the "Last seen by" panel.

The camera/JS decode path has no test infrastructure; these exercise the full server
contract instead — the manual-entry form on the scan page posts through the exact same
endpoint the scanner JS does.
"""

import pytest
from django.urls import reverse

from apps.inventory.models import Item, Location, ScanEvent
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab


@pytest.fixture
def lab(db):
    return create_lab(name="AG Baumann", item_id_prefix="AGB")


@pytest.fixture
def other_lab(db):
    return create_lab(name="AG Other", item_id_prefix="OTH")


def _member(email: str, lab, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


@pytest.fixture
def viewer(lab):
    return _member("view@x.de", lab, ["Viewer"])


def _make_item(lab, name="Tris buffer", **kwargs) -> Item:
    return Item.objects.create(lab=lab, human_id=lab.allocate_item_id(), name=name, **kwargs)


@pytest.mark.django_db
def test_scan_page_renders_form_and_scanner_assets(client, lab, viewer):
    client.force_login(viewer)
    resp = client.get(reverse("inventory:scan_page"))
    assert resp.status_code == 200
    assert reverse("inventory:scan_resolve").encode() in resp.content
    assert b"vendor/zxing.min.js" in resp.content
    assert b"js/scanner.js" in resp.content


@pytest.mark.django_db
def test_scan_page_requires_login(client, lab):
    resp = client.get(reverse("inventory:scan_page"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_resolve_normalizes_code_and_records_scan(client, lab, viewer):
    shelf = Location.objects.create(lab=lab, name="Shelf 3")
    item = _make_item(lab, location=shelf)
    client.force_login(viewer)
    assert item.human_id == "AGB-00001"
    # Sloppy input (lowercase, no hyphen, no zero padding) must still resolve.
    resp = client.post(reverse("inventory:scan_resolve"), {"code": "agb1"})
    assert resp.status_code == 302
    assert resp["Location"] == reverse("inventory:item_detail", kwargs={"pk": item.pk})
    scan = ScanEvent.objects.get()
    assert scan.item == item
    assert scan.user == viewer
    assert scan.lab == lab
    assert scan.source == "search"
    assert scan.location == shelf


@pytest.mark.django_db
def test_resolve_unknown_code_falls_back_to_search(client, lab, viewer):
    client.force_login(viewer)
    resp = client.post(reverse("inventory:scan_resolve"), {"code": "AGB-99999"})
    assert resp.status_code == 302
    assert resp["Location"] == f"{reverse('inventory:item_list')}?q=AGB-99999"
    assert ScanEvent.objects.count() == 0


@pytest.mark.django_db
def test_resolve_matches_legacy_human_id_verbatim(client, lab, viewer):
    # Imported items keep their legacy ID as human_id; it doesn't match the lab
    # prefix, but a label encoding it must still resolve directly (case-insensitively).
    item = Item.objects.create(lab=lab, human_id="pr-0213", name="Imported acetone")
    client.force_login(viewer)
    resp = client.post(reverse("inventory:scan_resolve"), {"code": "PR-0213"})
    assert resp.status_code == 302
    assert resp["Location"] == reverse("inventory:item_detail", kwargs={"pk": item.pk})
    assert ScanEvent.objects.get().item == item


@pytest.mark.django_db
def test_resolve_ambiguous_case_variants_fall_back_to_search(client, lab, viewer):
    Item.objects.create(lab=lab, human_id="pr-0213", name="Lower")
    Item.objects.create(lab=lab, human_id="PR-0213", name="Upper")
    client.force_login(viewer)
    resp = client.post(reverse("inventory:scan_resolve"), {"code": "Pr-0213"})
    assert resp.status_code == 302
    assert reverse("inventory:item_list") in resp["Location"]
    assert ScanEvent.objects.count() == 0


@pytest.mark.django_db
def test_resolve_malformed_code_falls_back_without_error(client, lab, viewer):
    client.force_login(viewer)
    resp = client.post(reverse("inventory:scan_resolve"), {"code": "garbage!!"})
    assert resp.status_code == 302
    assert reverse("inventory:item_list") in resp["Location"]
    assert ScanEvent.objects.count() == 0


@pytest.mark.django_db
def test_resolve_is_scoped_to_current_lab(client, lab, other_lab, viewer):
    foreign_item = _make_item(other_lab)
    client.force_login(viewer)
    # The foreign lab's code doesn't even match this lab's prefix -> treated as unknown.
    resp = client.post(reverse("inventory:scan_resolve"), {"code": foreign_item.human_id})
    assert resp.status_code == 302
    assert reverse("inventory:item_list") in resp["Location"]
    assert ScanEvent.objects.count() == 0


@pytest.mark.django_db
def test_resolve_rejects_get(client, lab, viewer):
    client.force_login(viewer)
    assert client.get(reverse("inventory:scan_resolve")).status_code == 405


@pytest.mark.django_db
def test_resolve_requires_login(client, lab):
    resp = client.post(reverse("inventory:scan_resolve"), {"code": "AGB-00001"})
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_detail_shows_last_seen_by(client, lab, viewer):
    item = _make_item(lab)
    ScanEvent.objects.create(lab=lab, item=item, user=viewer, location=item.location)
    client.force_login(viewer)
    resp = client.get(reverse("inventory:item_detail", kwargs={"pk": item.pk}))
    assert resp.status_code == 200
    assert b"Last seen by" in resp.content
    assert viewer.display_name.encode() in resp.content
    # {# ... #} template comments are single-line only; a multi-line one leaks as text.
    assert b"{#" not in resp.content


@pytest.mark.django_db
def test_detail_without_scans_says_never_scanned(client, lab, viewer):
    item = _make_item(lab)
    client.force_login(viewer)
    resp = client.get(reverse("inventory:item_detail", kwargs={"pk": item.pk}))
    assert b"never scanned" in resp.content


@pytest.mark.django_db
def test_scan_events_survive_user_deletion_and_order_newest_first(lab, viewer):
    item = _make_item(lab)
    first = ScanEvent.objects.create(lab=lab, item=item, user=viewer)
    second = ScanEvent.objects.create(lab=lab, item=item, user=viewer)
    viewer.delete()
    scans = list(item.scan_events.all())
    assert [scan.pk for scan in scans] == [second.pk, first.pk]
    assert all(scan.user is None for scan in scans)
