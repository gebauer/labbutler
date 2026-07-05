"""Self-approval: gating, the service (approval + audit + comment), and the view."""

import pytest
from django.urls import reverse

from apps.audit.models import AuditEntry
from apps.comments.models import Comment
from apps.procurement import services
from apps.procurement.models import Request
from apps.tenancy.models import User
from apps.tenancy.services import add_member, create_lab

Status = Request.Status


@pytest.fixture
def lab(db):
    return create_lab(name="Proc Lab", item_id_prefix="LB")


def _user(lab, email: str, roles: list[str]) -> User:
    user = User.objects.create_user(username="", email=email, password="pw")
    add_member(user=user, lab=lab, role_names=roles)
    return user


def _request(lab, by, **kwargs) -> Request:
    return Request.objects.create(lab=lab, item_name="Tips", requested_by=by, **kwargs)


@pytest.mark.django_db
def test_can_self_approve_only_own_pending_with_permission(lab):
    member = _user(lab, "member@x.de", ["Member"])  # has self_approve, not approve_request
    other = _user(lab, "other@x.de", ["Member"])
    own = _request(lab, member)

    assert services.can_self_approve(member, own) is True
    # Not someone else's request.
    assert services.can_self_approve(other, own) is False
    # Not once it has left the requested state.
    own.status = Status.APPROVED
    assert services.can_self_approve(member, own) is False


@pytest.mark.django_db
def test_user_with_both_permissions_gets_both_actions_on_own_request(lab):
    # Holding approve_request and self_approve (e.g. via Member + Lab manager roles)
    # offers both actions: self-approve leaves an audit comment, plain approve does not.
    approver = _user(lab, "boss@x.de", ["Member", "Lab manager"])
    own = _request(lab, approver)
    assert services.can_self_approve(approver, own) is True
    assert any(t.action == "approve" for t in services.available_transitions(approver, own))
    # Self-approve stays limited to one's own requests, even for approvers.
    other = _request(lab, _user(lab, "other@x.de", ["Member"]))
    assert services.can_self_approve(approver, other) is False


@pytest.mark.django_db
def test_self_approve_approves_audits_and_comments(lab):
    member = _user(lab, "member@x.de", ["Member"])
    req = _request(lab, member)

    services.self_approve(req, actor=member, note="OK'd by Dr. Baumann in the corridor")

    req.refresh_from_db()
    assert req.status == Status.APPROVED
    assert req.approver == member
    comment = Comment.for_object(req).get()
    assert comment.author == member
    assert "Self-approved" in comment.body
    assert "corridor" in comment.body
    assert AuditEntry.objects.filter(
        lab=lab, target_type="Request", action="procurement.request_self_approved"
    ).exists()


@pytest.mark.django_db
def test_self_approve_rejects_non_pending(lab):
    member = _user(lab, "member@x.de", ["Member"])
    req = _request(lab, member, status=Status.ORDERED)
    with pytest.raises(services.TransitionError):
        services.self_approve(req, actor=member)


@pytest.mark.django_db
def test_view_requires_confirmation(client, lab):
    member = _user(lab, "member@x.de", ["Member"])
    req = _request(lab, member)
    client.force_login(member)
    url = reverse("procurement:request_self_approve", args=[req.pk])

    # GET shows the dialog.
    assert client.get(url).status_code == 200
    # POST without the confirm box changes nothing.
    resp = client.post(url, {})
    assert resp.status_code == 200
    req.refresh_from_db()
    assert req.status == Status.REQUESTED
    assert not Comment.for_object(req).exists()


@pytest.mark.django_db
def test_view_confirmed_self_approves(client, lab):
    member = _user(lab, "member@x.de", ["Member"])
    req = _request(lab, member)
    client.force_login(member)
    url = reverse("procurement:request_self_approve", args=[req.pk])

    resp = client.post(url, {"confirm": "1", "note": "verbal ok"})
    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.status == Status.APPROVED
    assert Comment.for_object(req).count() == 1


@pytest.mark.django_db
def test_view_forbids_other_users(client, lab):
    member = _user(lab, "member@x.de", ["Member"])
    other = _user(lab, "other@x.de", ["Member"])
    req = _request(lab, member)
    client.force_login(other)
    url = reverse("procurement:request_self_approve", args=[req.pk])
    assert client.get(url).status_code == 403
