from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.tenancy.models import Lab
from labbutler.abstract import TimeStampedModel

# Currencies offered in price dropdowns. The DB columns stay free-form CharFields so
# imported historical data with other codes survives; these are just the typeable set.
CURRENCIES = ["EUR", "USD", "GBP", "CHF", "JPY"]


class Vendor(TimeStampedModel):
    """A supplier — just a name, quick-created inline during ordering."""

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="vendors")
    name = models.CharField(max_length=200)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lab", "name"], name="unique_vendor_per_lab"),
        ]

    def __str__(self) -> str:
        return self.name


class LabDefaultable(TimeStampedModel):
    """Per-lab row where at most one can be the default (preselected on new requests).

    Concrete models must add the partial unique constraint on (lab, is_default=True)
    themselves so each carries a stable, explicit constraint name.
    """

    is_default = models.BooleanField(default=False)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs) -> None:
        # Becoming the default demotes the previous one, keeping the constraint happy.
        if self.is_default:
            type(self).objects.filter(lab=self.lab, is_default=True).exclude(pk=self.pk).update(
                is_default=False
            )
        super().save(*args, **kwargs)

    @classmethod
    def default_for(cls, lab: Lab):
        """The lab's default row, or its only row if just one exists."""
        rows = list(cls.objects.filter(lab=lab).order_by("-is_default")[:2])
        if not rows:
            return None
        if rows[0].is_default or len(rows) == 1:
            return rows[0]
        return None


class Budget(LabDefaultable):
    """A cost centre (Kostenstelle / grant). Each request is charged to exactly one."""

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="budgets")
    number = models.CharField("Kostenstelle", max_length=64)
    name = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="budgets",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lab", "number"], name="unique_budget_number_per_lab"),
            models.UniqueConstraint(
                fields=["lab"],
                condition=models.Q(is_default=True),
                name="unique_default_budget_per_lab",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.name}"


class ShippingAddress(LabDefaultable):
    """A delivery address; a request ships to one."""

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="shipping_addresses")
    label = models.CharField(max_length=200)
    address = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lab"],
                condition=models.Q(is_default=True),
                name="unique_default_shipping_address_per_lab",
            ),
        ]

    def __str__(self) -> str:
        return self.label


class Request(TimeStampedModel):
    """A single-item procurement request flowing through the approval/order workflow.

    Approval is separate from ordering; on check-in the request creates the inventory
    item(s) and links back. Totals are rough estimates (auto-calculated VAT), never
    accounting-grade.
    """

    class SignalWord(models.TextChoices):
        # Values must stay in lockstep with inventory.Item.SignalWord — they are
        # copied verbatim onto the created item at check-in.
        NONE = "", "None"
        WARNING = "warning", "Warning"
        DANGER = "danger", "Danger"

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        ORDERED = "ordered", "Ordered"
        DELIVERED = "delivered", "Delivered"
        RECEIVED = "received", "Received"
        CHECKED_IN = "checked_in", "Checked in"
        CANCELLED = "cancelled", "Cancelled"

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="requests")

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="requests_made",
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests_to_approve",
    )
    # Order-responsible person the request is deferred to (needs accept_forwards).
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests_assigned",
    )

    vendor = models.ForeignKey(
        Vendor, on_delete=models.SET_NULL, null=True, blank=True, related_name="requests"
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.SET_NULL, null=True, blank=True, related_name="requests"
    )
    shipping_address = models.ForeignKey(
        ShippingAddress,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests",
    )
    # The item created on check-in (back-link); and an item this was reordered from.
    created_item = models.OneToOneField(
        "inventory.Item",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_request",
    )
    source_item = models.ForeignKey(
        "inventory.Item",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reorder_requests",
    )

    item_name = models.CharField(max_length=500)
    catalog_number = models.CharField(max_length=128, blank=True)
    cas_number = models.CharField(max_length=64, blank=True)
    product_url = models.URLField(blank=True)

    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="EUR")
    pack_count = models.PositiveIntegerField(default=1)
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    includes_taxes = models.BooleanField(default=False)
    # Derived, auto-calculated — never hand-typed (see recalculate_totals()).
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    is_urgent = models.BooleanField(default=False)
    po_number = models.CharField("PO #", max_length=64, blank=True)
    quote_id = models.CharField(max_length=64, blank=True)
    expected_delivery = models.DateField(null=True, blank=True)
    comment = models.TextField(blank=True)

    # Historical workflow milestones, populated by the LabSuit orders import. Requests
    # created in-app leave these blank and rely on the auto created/updated timestamps.
    date_requested = models.DateField(null=True, blank=True)
    date_approved = models.DateField(null=True, blank=True)
    date_ordered = models.DateField(null=True, blank=True)
    date_cancelled = models.DateField(null=True, blank=True)
    date_received = models.DateField(null=True, blank=True)

    tags = models.ManyToManyField("inventory.Tag", related_name="requests", blank=True)

    # Optional GHS hazard data captured at request time; carried onto the inventory
    # item at check-in so safety info is known before the container arrives.
    signal_word = models.CharField(
        max_length=10, choices=SignalWord.choices, blank=True, default=""
    )
    storage_class = models.CharField("Lagerklasse (TRGS 510)", max_length=20, blank=True)
    hazards = models.ManyToManyField(
        "inventory.HazardStatement", related_name="requests", blank=True
    )

    def __str__(self) -> str:
        return f"{self.item_name} [{self.get_status_display()}]"

    def recalculate_totals(self, vat_rate: Decimal | None = None) -> None:
        """Recompute ``tax`` and ``total`` from the price fields.

        If taxes are NOT included, tax = (unit_price*pack + shipping) * vat_rate and
        total = subtotal + tax. If taxes ARE included, the entered price is gross:
        total is taken as-is and tax is only an informational back-calculation.
        """
        if vat_rate is None:
            vat_rate = self.lab.default_vat_rate
        subtotal = self.unit_price * self.pack_count + self.shipping_cost
        if self.includes_taxes:
            self.total = subtotal
            # Back-calculated portion of the gross that is VAT.
            self.tax = subtotal - (subtotal / (Decimal(1) + vat_rate))
        else:
            self.tax = subtotal * vat_rate
            self.total = subtotal + self.tax
