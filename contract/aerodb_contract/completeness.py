"""The model-completeness checklist (Master Plan §8.7), as data.

The producer's geometry audit fills the statuses; this module owns the LIST and validates the block.
Flags, not gates — except the items marked `required_for_release`, which `release publish` (and
lint's `completeness_required` check) refuse to ship `open`.
"""

from __future__ import annotations

from dataclasses import dataclass

CHECKLIST_VERSION = 1


@dataclass(frozen=True)
class Item:
    id: str
    doc: str
    required_for_release: bool


CHECKLIST: tuple[Item, ...] = (
    Item("reference_quantities", "S, b, cbar set explicitly (not OpenVSP defaults) and match the wing", True),
    Item("moment_reference_point", "the moment reference point is set from the campaign, not left at 0", True),
    Item("surfaces_present", "all seven control surfaces exist as OpenVSP subsurfaces", True),
    Item("surfaces_hinged", "every control surface has a hinge line and TE-down-positive sense verified", True),
    Item("surface_vocabulary", "VSPAERO control groups are named exactly per conventions.SURFACES, one group per surface", True),
    Item("flap_detents_defined", "flap detent angles in the campaign match the geometry's flap groups", True),
    Item("engine_geometry", "intake / nacelle / exhaust bodies present in the analysed set", False),
    Item("gear_geometry", "landing gear geometry present and in a set that can be toggled", False),
    Item("mass_ledger", "a component mass ledger exists for massprops", False),
    Item("airfoils_defined", "wing/tail sections carry the intended airfoils, not the OpenVSP default", False),
)

STATUSES = ("clear", "open", "waived")


def validate_flags(flags: list[dict]) -> list[str]:
    """Structural check of a `completeness.flags` block against the list: every item present
    exactly once, statuses legal, waived items carry a note."""
    errors = []
    seen = {}
    ids = {it.id for it in CHECKLIST}
    for i, f in enumerate(flags):
        item = f.get("item")
        if item not in ids:
            errors.append(f"completeness.flags[{i}]: unknown item {item!r}")
            continue
        if item in seen:
            errors.append(f"completeness.flags: {item!r} listed twice")
        seen[item] = f
        if f.get("status") not in STATUSES:
            errors.append(f"completeness.flags[{i}]: bad status {f.get('status')!r}")
        if f.get("status") == "waived" and not f.get("note"):
            errors.append(f"completeness.flags[{i}]: waived without a note")
    for it in CHECKLIST:
        if it.id not in seen:
            errors.append(f"completeness.flags: missing item {it.id!r}")
    return errors


def release_blockers(flags: list[dict]) -> list[str]:
    """Items that are required for release and not clear (waived counts as not clear here — a
    waiver on a required item is a decision someone has to sign, and lint says so)."""
    req = {it.id for it in CHECKLIST if it.required_for_release}
    return [f["item"] for f in flags if f.get("item") in req and f.get("status") != "clear"]
