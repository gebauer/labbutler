# Importing data

The importer is what makes LabButler usable on day one: it migrates an existing
inventory from another system (LabSuit, Labguru, or any spreadsheet export) and
items keep their original IDs — so no physical container needs relabelling.
Running imports requires the `import_inventory` permission.

## The import wizard

**Imports** in the navigation bar starts a four-step wizard:

1. **Upload** a spreadsheet (`.xlsx` or `.xlsm`).
2. **Map columns** — LabSuit exports are recognised automatically and need no
   mapping; for other sources LabButler guesses a mapping from the column headers,
   which you then review and adjust.
3. **Dry-run preview** — nothing is written yet. You see exactly what would happen:
   e.g. *1,840 OK, 28 warnings, 6 errors*, with each warning and error explained
   row by row. Fix the spreadsheet and re-upload, or proceed if the result looks
   right.
4. **Commit** — the plan is applied and the items appear in your inventory.

!!! warning "Spreadsheet format"
    The wizard accepts `.xlsx`/`.xlsm` only. If your export is a CSV, open it in
    Excel or LibreOffice and save it as `.xlsx` first.

## The LabSuit profile

The built-in LabSuit profile understands the real-world messiness of LabSuit
exports:

- The export layout itself — control columns and the *Import Instructions* sheet.
- **Mixed price formats**: `18.80EUR`, `EUR 109.00`, `$ 500.00` all parse.
- **European dates** (`DD-MM-YYYY`).
- **Dirty three-level locations**, rebuilt into the location tree.
- The **TAGS soup**: GHS H/P/EUH codes, signal words, WGK, and storage classes
  buried among free-form tags are split out into LabButler's structured hazard
  fields; what remains becomes ordinary tags.
- Vendors and owners are matched or created as needed.

Crucially, each item's **original LabSuit serial becomes its frozen LabButler ID**,
and re-importing the same export updates existing items instead of duplicating them
(upsert on the legacy serial). Existing labels on physical containers stay valid.

## The generic mapper

For any other source (Labguru, a home-grown Excel list, …), the generic path lets
you map any column to any item field (name, location, prices, dates, tags, custom
fields, …). Two differences from the LabSuit path:

- Rows get a **freshly allocated frozen ID**. Map your old system's ID column to
  the **Legacy ID / serial** field and it stays searchable, so containers still
  labelled with the old ID remain findable — no relabelling needed here either.
- Generic imports always **create** items — there is no deduplication, so importing
  the same file twice creates duplicates. Use the dry-run preview to check before
  committing.

## Importing LabSuit order history

Past orders can be migrated too, so budget reporting has history from day one. This
is a command-line import run by the server administrator:

```bash
python manage.py import_labsuit_orders <export.xlsx> ...
```

Imported requests keep their historical workflow dates (requested, approved,
ordered, received) rather than the import date. See
[Operation & maintenance](../admin-guide/maintenance.md#management-commands).
