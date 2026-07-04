# Inventory

The inventory is the shared, searchable record of everything physical in the lab.
The rule is simple: **one physical container = one record**. Two bottles of the same
chemical are two items, each with its own ID and label.

Viewing the inventory requires the `view_inventory` permission; creating, editing,
and deleting items (and locations, tags, custom fields) requires `manage_inventory`.

## The item list and search

**Inventory** in the navigation bar shows the item list for the current lab. The
search box filters live as you type — free-text search across items — and you can
narrow by **tag**. On a phone the table collapses to stacked cards, so lookups work
at the bench or in front of the fridge.

## What an item records

| Field | Notes |
|---|---|
| **ID** | Frozen human ID (`AGB-04821`) — assigned at creation, never changes |
| **Name** | Free text, e.g. *Ethanol absolute 99.9%* |
| **Location** | A node in the lab's location tree, shown as its full path |
| **Vendor** | Supplier, from the lab's supplier list |
| **Owner** | The responsible member |
| **Price & currency** | Informational, e.g. from the originating order |
| **Expiration date** | Drives the [expiry digest](notifications.md#expiry-digest) |
| **Lot / catalog / CAS number** | For reordering and identification |
| **Hazard data** | GHS statements, signal word, WGK, storage class — see below |
| **Tags** | Free-form labels, e.g. `antibody`, `2022` — an item can have many |
| **Custom fields** | Lab-defined extra fields — see below |
| **Barcode** | Optional scanned/entered barcode value |
| **Legacy serial** | The original LabSuit serial, kept searchable after import |

Items also carry **file attachments** (safety data sheets, manuals, certificates)
and a **comment thread** for notes and discussion.

### Frozen IDs and labels

New items get the next free ID in the lab's sequence (`PREFIX-NNNNN`); at creation
you can accept the suggestion or pick another free one. Once saved, the ID is
permanent — LabButler will never recompute it from the item's name, type, or any
other field, so the label on the physical container stays valid forever.

Every item detail page has a **print-friendly label page** with the frozen ID and
labelling instructions — open it and print, then fix the label to the container.

### Hazard data (GHS)

Hazard information is structured, not free text:

- **H / EUH / P statements** from the built-in GHS catalog (with English and German
  texts), shown with the matching GHS pictograms.
- **Signal word** — *Warning* or *Danger*.
- **WGK** — Wassergefährdungsklasse (German water hazard class).
- **Storage class** — Lagerklasse per TRGS 510.

When creating an item you can look up GHS data to fill these fields quickly. Attach
the SDS/MSDS PDF to the item so it is always one click away.

## Locations

Storage locations form a **tree of any depth** — typically room → cabinet/fridge →
shelf/tray. An item points at one node and is displayed with the full path, e.g.
`Room 376 / Fridge A / Shelf 2`. Filtering by a location includes everything below
it, so "what is in Room 376?" covers all its fridges and shelves.

Locations are managed under **Manage → Locations** (requires `manage_inventory`):
create, rename, re-parent, and delete nodes. Deleting a location does not delete the
items in it — they just lose their location assignment.

## Tags

Tags are free-form, multi-membership labels (`antibody`, `enzyme`, `2022`, …). An
item can carry any number of them; use them for whatever classification your lab
finds useful and filter the item list by them. Tags never affect an item's ID.

## Custom fields

Each lab can define **custom fields** (text, number, date, or boolean) under
**Manage → Custom fields**; values are stored per item. **Field presets** bundle
several fields under a name (e.g. *Chemical fields*) so a whole set can be applied
to an item in one step — a preset is pure convenience and is never stored as the
item's identity or type.

## Editing and deleting

Editing an item changes any field **except** the frozen ID. Deleting an item asks
for confirmation and is recorded — like every change — in the lab's immutable audit
trail with actor, timestamp, and what changed.

!!! tip "Items usually create themselves"
    In day-to-day use most new items are *not* typed in by hand: they are created
    automatically when a delivered order is
    [checked in](procurement.md#receiving-a-delivery), pre-filled from the request.
    Manual creation is mainly for things that never went through procurement.
