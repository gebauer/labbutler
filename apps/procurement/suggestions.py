"""Route and PO-refresh suggestion engine — pure functions that nudge, never mutate.

Core principle of the central-purchasing workflow: LabButler computes and suggests, but
never changes procurement state on the basis of financial values. Both functions here
return a payload for the UI to render as a nudge; acting on it is always a manual human
step. They are computed from current field values at render/save time and never cached
into state, so making requests editable after approval later requires no changes here.

The two suggestions are deliberately independent: a price rise can cross the route
threshold without invalidating the PO, and vice versa — render them separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from .models import PurchaseOrder, Request


def central_purchasing_threshold(lab) -> Decimal:
    """Net total above which CENTRAL is suggested; lab override, else instance default."""
    if lab.central_purchasing_threshold_net is not None:
        return lab.central_purchasing_threshold_net
    return Decimal(str(settings.LABBUTLER_CENTRAL_PURCHASING_THRESHOLD_NET))


def po_deviation_threshold(lab) -> Decimal:
    """Percent price drift above which a PO refresh is suggested (sub-threshold is noise)."""
    if lab.po_deviation_threshold_pct is not None:
        return lab.po_deviation_threshold_pct
    return Decimal(str(settings.LABBUTLER_PO_DEVIATION_THRESHOLD_PCT))


def eu_countries() -> frozenset[str]:
    """ISO 3166 alpha-2 codes counted as EU for the non-EU vendor signal."""
    return frozenset(code.strip().upper() for code in settings.LABBUTLER_EU_COUNTRIES)


@dataclass(frozen=True)
class RouteSuggestion:
    route: str
    # Human-readable, shown verbatim in the nudge; empty when DIRECT is suggested.
    reasons: tuple[str, ...]


def suggest_route(req: Request) -> RouteSuggestion:
    """Suggest CENTRAL when the net total exceeds the threshold or the vendor is non-EU.

    The basis is always net (never gross, so the tax entry mode can't flip the
    suggestion). A vendor without a country contributes no signal at all — unknown
    origin never nudges.
    """
    reasons: list[str] = []
    threshold = central_purchasing_threshold(req.lab)
    net = req.net_total
    if net > threshold:
        reasons.append(f"Net total {net} {req.currency} is above the {threshold} € threshold")
    country = (req.vendor.country or "").strip().upper() if req.vendor_id else ""
    if country and country not in eu_countries():
        reasons.append(f"Vendor is outside the EU ({country})")
    if reasons:
        return RouteSuggestion(Request.Route.CENTRAL, tuple(reasons))
    return RouteSuggestion(Request.Route.DIRECT, ())


@dataclass(frozen=True)
class PORefreshSuggestion:
    should_refresh: bool
    deviation_pct: Decimal


def suggest_po_refresh(po: PurchaseOrder, current_net: Decimal) -> PORefreshSuggestion:
    """Suggest recreating the PO when the price drifted beyond the deviation threshold.

    The baseline is the net snapshot frozen at PO creation — never recomputed. POs carry
    approximate prices, so drift at or below the threshold is noise and yields no nudge.
    """
    if po.po_snapshot_net == 0:
        # No meaningful baseline: any non-zero price counts as a full deviation.
        deviation = Decimal("100") if current_net else Decimal("0")
    else:
        deviation = abs(current_net - po.po_snapshot_net) / po.po_snapshot_net * 100
    deviation = deviation.quantize(Decimal("0.1"))
    return PORefreshSuggestion(deviation > po_deviation_threshold(po.request.lab), deviation)
