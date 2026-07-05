"""Human-ID helpers for the preprinted-label workflow.

Labels are preprinted and handed out, so an item's ID is *chosen* — picked from the free
pool or typed in — rather than silently auto-incremented. These helpers suggest the next
free ``{PREFIX}-NNNNN`` IDs and normalise/validate a manually entered one. IDs stay frozen
once assigned (see the identity rule in the spec).
"""

from __future__ import annotations

import re

from apps.tenancy.models import Lab

_WIDTH = 5


def _pattern(prefix: str) -> re.Pattern:
    # Accept an optional hyphen and leading zeros, case-insensitively: AGB-00001, agb1, AGB-1.
    return re.compile(rf"^{re.escape(prefix)}-?0*(\d+)$", re.IGNORECASE)


def _format(prefix: str, number: int) -> str:
    return f"{prefix}-{number:0{_WIDTH}d}"


def _used_numbers(lab: Lab) -> set[int]:
    """Numbers already taken by ``{PREFIX}-…`` items (legacy serials are ignored)."""
    pattern = _pattern(lab.item_id_prefix)
    numbers: set[int] = set()
    for human_id in lab.items.values_list("human_id", flat=True):
        match = pattern.match(human_id or "")
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def suggest_ids(lab: Lab, count: int = 10) -> list[str]:
    """The next ``count`` free IDs after the highest one used (gaps are skipped)."""
    used = _used_numbers(lab)
    number = max((max(used) if used else 0) + 1, lab.next_item_number)
    suggestions: list[str] = []
    while len(suggestions) < count:
        if number not in used:
            suggestions.append(_format(lab.item_id_prefix, number))
        number += 1
    return suggestions


def normalize_item_id(lab: Lab, raw: str) -> str:
    """Normalise a manually entered ID to ``{PREFIX}-NNNNN``; raise ``ValueError`` if malformed."""
    match = _pattern(lab.item_id_prefix).match((raw or "").strip())
    if not match:
        raise ValueError(f"ID must look like {_format(lab.item_id_prefix, 1)}.")
    return _format(lab.item_id_prefix, int(match.group(1)))


def item_id_taken(lab: Lab, human_id: str) -> bool:
    return lab.items.filter(human_id=human_id).exists()


def id_sequence(lab: Lab, start_id: str, count: int) -> list[str]:
    """``count`` consecutive IDs starting at ``start_id`` (which may be unnormalised).

    Labels are preprinted, so the sequence is strictly consecutive — numbers already
    in use are *not* skipped (reprinting an existing label is legitimate).
    """
    match = _pattern(lab.item_id_prefix).match((start_id or "").strip())
    if not match:
        raise ValueError(f"ID must look like {_format(lab.item_id_prefix, 1)}.")
    start = int(match.group(1))
    return [_format(lab.item_id_prefix, number) for number in range(start, start + count)]
