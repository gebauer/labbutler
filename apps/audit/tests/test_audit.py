import pytest

from apps.audit.models import AuditEntry
from apps.tenancy.services import create_lab


@pytest.mark.django_db
def test_record_creates_entry_from_instance():
    lab = create_lab(name="Audit Lab", item_id_prefix="AL")
    entry = AuditEntry.record(lab=lab, action="lab.created", target=lab)
    assert entry.target_type == "Lab"
    assert entry.target_id == str(lab.pk)
    assert entry.action == "lab.created"


@pytest.mark.django_db
def test_entries_are_append_only():
    lab = create_lab(name="Immutable Lab", item_id_prefix="IL")
    entry = AuditEntry.record(lab=lab, action="x", target=lab)
    entry.action = "tampered"
    with pytest.raises(ValueError):
        entry.save()
