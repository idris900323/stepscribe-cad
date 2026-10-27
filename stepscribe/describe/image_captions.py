# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Plain-text captions for the extra images, computed from the report and the file name alone.

Nothing here reads a part name from the file: a caption holds IDs, numbers and fixed words, so a
non-vision AI gets the facts of the picture and a hostile name cannot reach the image index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from stepscribe.describe.phrases import fmt
from stepscribe.models.schema import Contact, Part, Report, WeakSpot

MAX_HOLE_LABELS = 40  # holes named on a hole map (the rest stay in the hole table)
MAX_SPOT_ROWS = 12

# file suffix -> image type
KINDS = {
    "holes": "hole map",
    "views": "three-view drawing",
    "weak": "weak-spot overlay",
    "features": "feature highlight",
    "section": "section view",
    "contacts": "contact map",
    "links": "link colour map",
    "kinematic": "kinematic diagram",
}
_NAME = re.compile(r"^images/parts/(PRT\d+)_(holes|views|weak|features|section)\.png$")
_ASSEMBLY = re.compile(r"^images/(contact_map|link_map)\.png$")


@dataclass
class Caption:
    """What an image shows, which IDs it contains and which text section it pairs with."""

    kind: str
    what: str
    ids: list[str]
    pairs: str


def part_file_hint(part_id: str) -> str:
    return f"03_parts/{part_id}_*.md"


def part_weak_spots(report: Report, part: Part) -> list[WeakSpot]:
    """Weak spots that name this part (the first ref of a part-level finding is the part's ID)."""
    u = report.understanding
    return [w for w in u.weak_spots if part.id in w.refs] if u is not None else []


def hole_pattern_of(part: Part) -> dict[str, str]:
    """Hole ID -> pattern ID, where the hole belongs to a recognised pattern."""
    out: dict[str, str] = {}
    for pat in part.hole_patterns:
        for hid in pat.hole_ids:
            out.setdefault(hid, pat.id)
    return out


def hole_label(hole, pattern_id: str | None = None) -> str:  # type: ignore[no-untyped-def]
    """'H003 dia 5.1', plus the pattern ID when the hole is part of a pitched pattern."""
    text = f"{hole.id} dia {fmt(hole.diameter_mm)}"
    return f"{text} {pattern_id}" if pattern_id else text


def _holes_caption(part: Part) -> Caption:
    pats = hole_pattern_of(part)
    shown = part.holes[:MAX_HOLE_LABELS]
    parts = [hole_label(h, pats.get(h.id)) for h in shown]
    text = (
        f"Part {part.id} seen along its main hole axis. The holes are circled "
        "(red = through hole, blue = blind hole) and named with their ID and diameter in mm: "
        + "; ".join(parts)
        + ". A hole that faces another way and is hidden from this view is listed but not circled."
    )
    if len(part.holes) > len(shown):
        text += f" {len(part.holes) - len(shown)} more holes are in the hole table only."
    for pat in part.hole_patterns:
        pitch = f", pitch {fmt(pat.pitch_mm)} mm" if pat.pitch_mm else ""
        text += (
            f" Pattern {pat.id}: {pat.kind}, {pat.count} holes ({', '.join(pat.hole_ids)}){pitch}."
        )
    return Caption(
        "hole map",
        text,
        [part.id, *[h.id for h in shown], *[p.id for p in part.hole_patterns]],
        f"{part_file_hint(part.id)}, section Holes",
    )


def _views_caption(part: Part) -> Caption:
    a, b, c = (fmt(v) for v in part.obb.size_sorted)
    text = (
        f"Part {part.id} in three orthographic views (front, top, right). The overall width and "
        "height of a view are drawn as dimension lines in mm where the view is large enough to "
        f"hold them; the overall size is also written on the sheet. Oriented bounding box {a} x "
        f"{b} x {c} mm."
    )
    return Caption("three-view drawing", text, [part.id], f"{part_file_hint(part.id)}, header")


def _weak_caption(report: Report, part: Part) -> Caption:
    spots = part_weak_spots(report, part)
    rows = []
    ids = [part.id]
    for w in spots[:MAX_SPOT_ROWS]:
        value = f", {fmt(w.value, 2)} {w.unit or ''}".rstrip() if w.value is not None else ""
        holes = [r for r in w.refs if r != part.id]
        rows.append(
            f"{w.id} ({w.severity}, {w.category}{value}; refs {', '.join(holes) or part.id})"
        )
        ids += [w.id, *holes]
    text = (
        f"Part {part.id} drawn grey with its weak spots marked by severity colour "
        "(red high, orange medium, yellow low, blue info): " + "; ".join(rows) + "."
    )
    if len(spots) > MAX_SPOT_ROWS:
        text += f" {len(spots) - MAX_SPOT_ROWS} more are in the weak-spot table only."
    if any(w.category == "edge_distance" for w in spots):
        text += (
            " For an edge-distance finding the black line runs from the hole wall to the nearest "
            "edge and its length in mm is written beside it (measured in 3D, so it can look short "
            "when it runs along the viewing direction)."
        )
    return Caption(
        "weak-spot overlay",
        text,
        list(dict.fromkeys(ids)),
        "05_understanding.md, weak spots; " + part_file_hint(part.id),
    )


AXIS_LETTERS = "xyz"


def has_inner_features(part: Part) -> bool:
    return bool(part.holes or part.cutouts or part.pockets)


def section_plane(part: Part) -> tuple[int, float]:
    """(axis index, offset in mm in the part frame) of the plane the section view cuts along.

    Through the axis of the widest hole, perpendicular to the world axis that is most nearly square
    to it, so the cut runs along the bore and shows its wall; with no hole, across the longest
    extent at its middle."""
    lo = [part.bbox.min.x, part.bbox.min.y, part.bbox.min.z]
    hi = [part.bbox.max.x, part.bbox.max.y, part.bbox.max.z]
    if part.holes:
        h = max(part.holes, key=lambda x: (x.diameter_mm, x.id))
        d = [abs(h.axis.direction.x), abs(h.axis.direction.y), abs(h.axis.direction.z)]
        axis = d.index(min(d))
        return axis, [h.axis.origin.x, h.axis.origin.y, h.axis.origin.z][axis]
    ext = [b - a for a, b in zip(lo, hi, strict=True)]
    axis = ext.index(max(ext))
    return axis, 0.5 * (lo[axis] + hi[axis])


def _section_caption(part: Part) -> Caption:
    axis, offset = section_plane(part)
    letter = AXIS_LETTERS[axis]
    text = (
        f"Part {part.id} cut by the plane {letter} = {fmt(offset, 2)} mm (part frame). The material on "
        f"the + {letter} side is removed and the cut is seen from that side; the cut face is red. "
        "It shows the wall thickness and the inside along that plane."
    )
    return Caption("section view", text, [part.id], f"{part_file_hint(part.id)}, header and Holes")


def _features_caption(part: Part) -> Caption:
    families = [
        ("holes (red rings)", [h.id for h in part.holes]),
        (
            "cut-outs, slots and pockets (blue dots)",
            [c.id for c in part.cutouts]
            + [s.id for s in part.slots if not s.cutout_id]
            + [p.id for p in part.pockets if not p.cutout_id],
        ),
        ("bosses (orange dots)", [b.id for b in part.bosses]),
        ("fillets (green dots)", [f.id for f in part.fillets[:12]]),
        ("chamfers (purple dots)", [c.id for c in part.chamfers[:12]]),
    ]
    rows = [f"{name}: {', '.join(ids[:20])}" for name, ids in families if ids]
    text = (
        f"Part {part.id} in an isometric view with its features marked by family and named by ID: "
        + "; ".join(rows)
        + ". Only the first 12 fillets and 12 chamfers are marked, and a feature on a face turned "
        "away from the view is not marked (the feature tables list everything)."
    )
    ids = [part.id] + [i for _n, group in families for i in group[:20]]
    return Caption(
        "feature highlight", text, ids, f"{part_file_hint(part.id)}, sections Holes to Fillets"
    )


MAX_CONTACTS = 12


def selected_contacts(report: Report) -> list[Contact]:
    """The touching pairs the contact map shows: faces and fits (not near misses or edge touches),
    largest patch first, at most MAX_CONTACTS."""
    if report.assembly is None:
        return []
    real = [c for c in report.assembly.contacts if c.kind in ("planar_face", "cylindrical_fit")]
    real.sort(key=lambda c: (-(c.contact_area_mm2 or 0.0), c.id))
    return real[:MAX_CONTACTS]


def _contacts_caption(report: Report) -> Caption:
    rows = []
    ids = []
    for c in selected_contacts(report):
        area = f", patch {fmt(c.contact_area_mm2)} mm2" if c.contact_area_mm2 else ""
        rows.append(f"{c.id} {c.instance_a} - {c.instance_b} ({c.kind}{area})")
        ids += [c.id, c.instance_a, c.instance_b]
    total = len(report.assembly.contacts) if report.assembly else 0
    text = (
        "The assembly with the parts of the selected contacts in colour and every other part grey. "
        "Each contact ID sits where the bounding boxes of its two parts meet (a position estimate). "
        f"Contacts shown ({len(rows)} of {total}, largest patch first): " + "; ".join(rows) + "."
    )
    return Caption("contact map", text, list(dict.fromkeys(ids)), "02_assembly.md, contacts")


def _links_caption(report: Report) -> Caption:
    kin = report.understanding.kinematics if report.understanding else None
    links = kin.links if kin else []
    rows = [
        f"{g.id}{' (ground)' if g.is_ground else ''}: {', '.join(g.instance_ids)}" for g in links
    ]
    ids = [x for g in links for x in (g.id, *g.instance_ids)]
    text = (
        "The assembly coloured by rigid link group, the ground link grey; the label on each part "
        "is its link ID. Links and their instances: " + "; ".join(rows) + "."
    )
    return Caption("link colour map", text, ids, "05_understanding.md, kinematics")


def caption_for(rel: str, report: Report) -> Caption | None:
    """The caption of an extra image, or None when *rel* is not one of them."""
    am = _ASSEMBLY.match(rel)
    if am:
        return _contacts_caption(report) if am.group(1) == "contact_map" else _links_caption(report)
    m = _NAME.match(rel)
    if not m:
        return None
    part = next((p for p in report.parts if p.id == m.group(1)), None)
    if part is None:
        return None
    if m.group(2) == "holes":
        return _holes_caption(part)
    if m.group(2) == "views":
        return _views_caption(part)
    if m.group(2) == "weak":
        return _weak_caption(report, part)
    if m.group(2) == "features":
        return _features_caption(part)
    return _section_caption(part)


def caption_line(rel: str, report: Report) -> str:
    """The reference as it appears in the part / assembly Markdown: the path, plus the caption
    for an extra image (the basic images keep their plain reference)."""
    cap = caption_for(rel, report)
    return rel if cap is None else f"{rel}: {cap.what}"
