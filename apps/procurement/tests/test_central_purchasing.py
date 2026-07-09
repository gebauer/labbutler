"""Central-purchasing workflow tests: route guards, the PO lifecycle, re-routing,
and the mandatory (but reason-optional) route-override audit event."""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEntry
from apps.procurement import services
from apps.procurement.models import Budget, PurchaseOrder, Request, Vendor
from apps.procurement.services import TRANSITIONS, TransitionError, may_perform, perform_transition
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab

Status = Request.Status
Route = Request.Route


@pytest.fixture
def lab(db):
    return create_lab(name="Proc Lab", item_id_prefix="LB")


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")


def _user(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


def _pdf(name: str = "form.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")


def _request(lab, by, *, net="1500.00", route=Route.CENTRAL, status=Status.APPROVED, **kwargs):
    req = Request.objects.create(
        lab=lab,
        item_name="Zentrifuge",
        requested_by=by,
        unit_price=Decimal(net),
        procurement_route=route,
        status=status,
        **kwargs,
    )
    req.recalculate_totals()
    req.save()
    return req


def _audit(req, action):
    return AuditEntry.objects.filter(
        lab=req.lab, action=action, target_type="Request", target_id=str(req.pk)
    )


# --- PO lifecycle ---------------------------------------------------------------------


@pytest.mark.django_db
def test_create_po_freezes_snapshot_and_moves_to_po_created(lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)

    po = services.create_po(req, actor=member, upload=_pdf())

    req.refresh_from_db()
    assert req.status == Status.PO_CREATED
    assert po.po_snapshot_net == Decimal("1500.00")
    assert po.status == PurchaseOrder.Status.ACTIVE
    assert req.active_purchase_order() == po
    entry = _audit(req, "procurement.po_created").get()
    assert entry.changes["snapshot_net"] == "1500.00"
    assert entry.changes["source"] == "uploaded"


@pytest.mark.django_db
def test_create_po_requires_central_route_and_mutable_state(lab):
    member = _user(lab, "u@x.de", ["Member"])
    direct = _request(lab, member, route=Route.DIRECT)
    with pytest.raises(TransitionError):
        services.create_po(direct, actor=member, upload=_pdf())

    sent = _request(lab, member, status=Status.PO_SENT)
    with pytest.raises(TransitionError):
        services.create_po(sent, actor=member, upload=_pdf())


@pytest.mark.django_db
def test_recreating_po_supersedes_and_resets_to_po_created(lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    first = services.create_po(req, actor=member, upload=_pdf())
    services.upload_signed_po(req, actor=manager, upload=_pdf("signed.pdf"))
    req.refresh_from_db()
    assert req.status == Status.PO_SIGNED

    second = services.create_po(req, actor=member, upload=_pdf("corrected.pdf"))

    req.refresh_from_db()
    first.refresh_from_db()
    assert req.status == Status.PO_CREATED  # re-signing implied
    assert first.status == PurchaseOrder.Status.SUPERSEDED
    assert req.active_purchase_order() == second
    assert _audit(req, "procurement.po_superseded").get().changes["cause"] == "recreated"


@pytest.mark.django_db
def test_upload_signed_po_records_uploader(lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    po = services.create_po(req, actor=member, upload=_pdf())

    services.upload_signed_po(req, actor=manager, upload=_pdf("signed.pdf"))

    req.refresh_from_db()
    po.refresh_from_db()
    assert req.status == Status.PO_SIGNED
    assert po.signed_uploaded_by == manager
    assert po.signed_pdf
    assert _audit(req, "procurement.po_signed").exists()


@pytest.mark.django_db
def test_upload_signed_po_only_from_po_created(lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)  # Approved, no PO yet
    with pytest.raises(TransitionError):
        services.upload_signed_po(req, actor=manager, upload=_pdf())


# --- State machine guards ---------------------------------------------------------------


@pytest.mark.django_db
def test_order_blocked_on_central_route_until_po_sent(lab):
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)  # Approved, CENTRAL

    assert not may_perform(coordinator, req, TRANSITIONS["order"])
    with pytest.raises(TransitionError):
        perform_transition(req, "order", actor=coordinator)

    services.create_po(req, actor=member, upload=_pdf())
    services.upload_signed_po(req, actor=_user(lab, "m@x.de", ["Lab manager"]), upload=_pdf())
    perform_transition(req, "send_to_zk", actor=coordinator)
    req.refresh_from_db()
    assert req.status == Status.PO_SENT

    perform_transition(req, "order", actor=coordinator, zk_order_number="ZK-2026-042")
    req.refresh_from_db()
    assert req.status == Status.ORDERED
    assert req.zk_order_number == "ZK-2026-042"
    assert (
        _audit(req, "procurement.request_order").get().changes["zk_order_number"] == "ZK-2026-042"
    )


@pytest.mark.django_db
def test_send_to_zk_allowed_for_request_manager_without_permission(lab):
    member = _user(lab, "u@x.de", ["Member"])  # no send_po_to_central
    other = _user(lab, "o@x.de", ["Member"])
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    req = _request(lab, member, status=Status.PO_SIGNED)

    transition = TRANSITIONS["send_to_zk"]
    assert may_perform(member, req, transition)  # manager of their own request
    assert not may_perform(other, req, transition)
    assert may_perform(coordinator, req, transition)

    req.assigned_to = other
    req.save()
    assert may_perform(other, req, transition)  # assignee took over as manager
    assert not may_perform(member, req, transition)


@pytest.mark.django_db
def test_request_manager_is_assignee_then_requester(lab):
    member = _user(lab, "u@x.de", ["Member"])
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    req = _request(lab, member)
    assert services.request_manager(req) == member
    req.assigned_to = coordinator
    assert services.request_manager(req) == coordinator


# --- Route override (the one intentional friction point) -------------------------------


@pytest.mark.django_db
def test_direct_order_against_central_suggestion_writes_override_event(lab):
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, route=Route.DIRECT)  # net 1500 > threshold

    perform_transition(req, "order", actor=coordinator)

    entry = _audit(req, "procurement.route_suggestion_overridden").get()
    assert entry.changes["suggested_route"] == Route.CENTRAL
    assert entry.changes["chosen_route"] == Route.DIRECT
    assert entry.changes["reason_code"] == ""  # reason optional, event mandatory
    assert entry.changes["net_total"] == "1500.00"
    req.refresh_from_db()
    assert req.status == Status.ORDERED  # never blocks the action


@pytest.mark.django_db
def test_override_reason_recorded_when_given(lab):
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, route=Route.DIRECT)

    perform_transition(
        req,
        "order",
        actor=coordinator,
        override_reason_code="emergency",
        override_reason_text="23:00",
    )

    entry = _audit(req, "procurement.route_suggestion_overridden").get()
    assert entry.changes["reason_code"] == "emergency"
    assert entry.changes["reason_text"] == "23:00"


@pytest.mark.django_db
def test_no_override_event_without_central_suggestion(lab):
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, net="200.00", route=Route.DIRECT)

    perform_transition(req, "order", actor=coordinator)

    assert not _audit(req, "procurement.route_suggestion_overridden").exists()


# --- Re-routing -------------------------------------------------------------------------


@pytest.mark.django_db
def test_reroute_direct_to_central_records_route_changed(lab):
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, route=Route.DIRECT)

    services.reroute(req, actor=coordinator, to_route=Route.CENTRAL)

    req.refresh_from_db()
    assert req.procurement_route == Route.CENTRAL
    assert req.status == Status.APPROVED
    entry = _audit(req, "procurement.route_changed").get()
    assert entry.changes["from_route"] == Route.DIRECT
    assert entry.changes["to_route"] == Route.CENTRAL


@pytest.mark.django_db
def test_reroute_central_to_direct_supersedes_po_and_resets(lab):
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    po = services.create_po(req, actor=member, upload=_pdf())
    services.upload_signed_po(req, actor=manager, upload=_pdf())

    services.reroute(req, actor=coordinator, to_route=Route.DIRECT, reason_code="vendor_exception")

    req.refresh_from_db()
    po.refresh_from_db()
    assert req.status == Status.APPROVED
    assert req.procurement_route == Route.DIRECT
    assert po.status == PurchaseOrder.Status.SUPERSEDED
    assert req.active_purchase_order() is None
    assert _audit(req, "procurement.po_superseded").get().changes["cause"] == "rerouted"
    # Choosing direct against the (still valid) CENTRAL suggestion is also recorded.
    override = _audit(req, "procurement.route_suggestion_overridden").get()
    assert override.changes["reason_code"] == "vendor_exception"


@pytest.mark.django_db
def test_reroute_locked_from_po_sent_onwards(lab):
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, status=Status.PO_SENT)

    assert not services.can_reroute(coordinator, req)
    with pytest.raises(TransitionError):
        services.reroute(req, actor=coordinator, to_route=Route.DIRECT)


@pytest.mark.django_db
def test_reroute_rejects_same_or_unknown_route(lab):
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    with pytest.raises(TransitionError):
        services.reroute(req, actor=coordinator, to_route=Route.CENTRAL)
    with pytest.raises(TransitionError):
        services.reroute(req, actor=coordinator, to_route="carrier_pigeon")


@pytest.mark.django_db
def test_reroute_requires_permission(lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    assert not services.can_reroute(member, req)


# --- Views ------------------------------------------------------------------------------


def _login(client, lab, user):
    # get_current_lab falls back to the user's first lab, so force_login is enough here.
    client.force_login(user)


@pytest.mark.django_db
def test_po_upload_view_allows_the_request_manager(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    _login(client, lab, member)

    response = client.post(f"/requests/{req.pk}/po/upload/", {"po_pdf": _pdf()})

    assert response.status_code == 302
    req.refresh_from_db()
    assert req.status == Status.PO_CREATED


@pytest.mark.django_db
def test_po_upload_view_rejects_non_pdf(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    _login(client, lab, member)

    upload = SimpleUploadedFile("form.txt", b"not a pdf", content_type="text/plain")
    response = client.post(f"/requests/{req.pk}/po/upload/", {"po_pdf": upload})

    assert response.status_code == 302
    req.refresh_from_db()
    assert req.status == Status.APPROVED


@pytest.mark.django_db
def test_po_upload_view_forbidden_for_uninvolved_member(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    other = _user(lab, "o@x.de", ["Member"])
    req = _request(lab, member)
    _login(client, lab, other)

    response = client.post(f"/requests/{req.pk}/po/upload/", {"po_pdf": _pdf()})
    assert response.status_code == 403


@pytest.mark.django_db
def test_signed_upload_view_requires_sign_po(client, lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    services.create_po(req, actor=member, upload=_pdf())

    _login(client, lab, member)
    assert (
        client.post(f"/requests/{req.pk}/po/upload-signed/", {"po_pdf": _pdf()}).status_code == 403
    )

    _login(client, lab, manager)
    response = client.post(f"/requests/{req.pk}/po/upload-signed/", {"po_pdf": _pdf()})
    assert response.status_code == 302
    req.refresh_from_db()
    assert req.status == Status.PO_SIGNED


@pytest.mark.django_db
def test_po_download_serves_the_file(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    po = services.create_po(req, actor=member, upload=_pdf())
    _login(client, lab, member)

    response = client.get(f"/requests/{req.pk}/po/{po.pk}/unsigned/")
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment")
    assert b"".join(response.streaming_content) == b"%PDF-1.4 test"

    assert client.get(f"/requests/{req.pk}/po/{po.pk}/signed/").status_code == 404  # none yet


@pytest.mark.django_db
def test_reroute_view_requires_permission(client, lab):
    coordinator = _user(lab, "pc@x.de", ["Purchase coordinator"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, route=Route.DIRECT)

    _login(client, lab, member)
    assert client.post(f"/requests/{req.pk}/reroute/", {"to_route": "central"}).status_code == 403

    _login(client, lab, coordinator)
    response = client.post(f"/requests/{req.pk}/reroute/", {"to_route": "central"})
    assert response.status_code == 302
    req.refresh_from_db()
    assert req.procurement_route == Route.CENTRAL


@pytest.mark.django_db
def test_detail_page_shows_central_section_and_fill_summary(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    _login(client, lab, member)

    response = client.get(f"/requests/{req.pk}/")
    content = response.content.decode()
    assert "Central purchasing" in content
    assert "Form-fill summary" in content
    assert "data-copy" in content


@pytest.mark.django_db
def test_detail_page_shows_route_nudge_with_reasons(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member, route=Route.DIRECT)  # net 1500 suggests CENTRAL
    _login(client, lab, member)

    content = client.get(f"/requests/{req.pk}/").content.decode()
    assert "central purchasing" in content
    assert "above the" in content  # threshold reason rendered


@pytest.mark.django_db
def test_dashboard_shows_pos_to_sign_for_signers(client, lab):
    manager = _user(lab, "m@x.de", ["Lab manager"])
    member = _user(lab, "u@x.de", ["Member"])
    req = _request(lab, member)
    services.create_po(req, actor=member, upload=_pdf())

    _login(client, lab, manager)
    assert "Purchase orders to sign" in client.get("/").content.decode()

    _login(client, lab, member)
    assert "Purchase orders to sign" not in client.get("/").content.decode()


# --- Bypass confirmation at form save -----------------------------------------------


def _form_payload(vendor, budget, **overrides) -> dict:
    payload = {
        "item_name": "Ultracentrifuge rotor",
        "vendor": vendor.pk,
        "budget": budget.pk,
        "currency": "EUR",
        "unit_price": "1500.00",  # net (taxes not included) — above the 1000 € default
        "pack_count": "1",
        "shipping_cost": "0",
        "procurement_route": Route.DIRECT,
        "tags": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_create_keeping_direct_against_suggestion_records_override(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    vendor = Vendor.objects.create(lab=lab, name="ACME", country="DE")
    budget = Budget.objects.create(lab=lab, number="KST-1", name="Core")
    _login(client, lab, member)

    response = client.post(
        "/requests/new/",
        _form_payload(
            vendor,
            budget,
            override_reason_code="emergency",
            override_reason_text="Freezer died",
        ),
    )

    assert response.status_code == 302
    req = Request.objects.get(item_name="Ultracentrifuge rotor")
    event = _audit(req, "procurement.route_suggestion_overridden").get()
    assert event.changes["suggested_route"] == Route.CENTRAL
    assert event.changes["chosen_route"] == Route.DIRECT
    assert event.changes["reason_code"] == "emergency"
    assert event.changes["reason_text"] == "Freezer died"


@pytest.mark.django_db
def test_create_below_threshold_direct_records_no_override(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    vendor = Vendor.objects.create(lab=lab, name="ACME", country="DE")
    budget = Budget.objects.create(lab=lab, number="KST-1", name="Core")
    _login(client, lab, member)

    response = client.post("/requests/new/", _form_payload(vendor, budget, unit_price="100.00"))

    assert response.status_code == 302
    req = Request.objects.get(item_name="Ultracentrifuge rotor")
    assert not _audit(req, "procurement.route_suggestion_overridden").exists()


@pytest.mark.django_db
def test_create_following_the_suggestion_records_no_override(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    vendor = Vendor.objects.create(lab=lab, name="ACME", country="DE")
    budget = Budget.objects.create(lab=lab, number="KST-1", name="Core")
    _login(client, lab, member)

    response = client.post(
        "/requests/new/", _form_payload(vendor, budget, procurement_route=Route.CENTRAL)
    )

    assert response.status_code == 302
    req = Request.objects.get(item_name="Ultracentrifuge rotor")
    assert req.procurement_route == Route.CENTRAL
    assert not _audit(req, "procurement.route_suggestion_overridden").exists()


@pytest.mark.django_db
def test_edit_keeping_direct_against_suggestion_records_override(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    vendor = Vendor.objects.create(lab=lab, name="ACME", country="DE")
    budget = Budget.objects.create(lab=lab, number="KST-1", name="Core")
    req = _request(
        lab,
        member,
        net="100.00",
        route=Route.DIRECT,
        status=Status.REQUESTED,
        vendor=vendor,
        budget=budget,
    )
    _login(client, lab, member)

    # Raising the price across the threshold while keeping DIRECT is the same
    # friction point as at creation — the event is recorded on save.
    response = client.post(
        f"/requests/{req.pk}/edit/",
        _form_payload(vendor, budget, item_name=req.item_name, unit_price="1500.00"),
    )

    assert response.status_code == 302
    event = _audit(req, "procurement.route_suggestion_overridden").get()
    assert event.changes["suggested_route"] == Route.CENTRAL
    assert event.changes["net_total"] == "1500.00"


@pytest.mark.django_db
def test_form_page_serves_suggestion_config_and_bypass_modal(client, lab):
    member = _user(lab, "u@x.de", ["Member"])
    Vendor.objects.create(lab=lab, name="US Vendor", country="US")
    Budget.objects.create(lab=lab, number="KST-1", name="Core")
    _login(client, lab, member)

    content = client.get("/requests/new/").content.decode()
    assert "route-suggestion-config" in content
    assert '"threshold": "1000' in content
    assert '"US"' in content  # vendor country map for the client-side non-EU signal
    assert "data-route-override-modal" in content
    assert "data-route-nudge" in content
    for code in services.OVERRIDE_REASONS:
        assert code in content
