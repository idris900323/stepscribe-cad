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
from stepscribe.models.schema import Part, Report

MAX_HOLE_LABELS = 40  # holes named on a hole map (the rest stay in the hole table)

# file suffix -> image type
KINDS = {"holes": "hole map", "views": "three-view drawing"}
_NAME = re.compile(r"^images/parts/(PRT\d+)_(holes|views)\.png$")


@dataclass
class Caption:
    """What an image shows, which IDs it contains and which text section it pairs with."""

    kind: str
    what: str
    ids: list[str]
    pairs: str


def part_file_hint(part_id: str) -> str:
    return f"03_parts/{part_id}_*.md"


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
        f"Part {part.id} seen along its main hole axis. Every labelled hole is circled "
        "(red = through hole, blue = blind hole) and named with its ID and diameter in mm: "
        + "; ".join(parts)
        + "."
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


def caption_for(rel: str, report: Report) -> Caption | None:
    """The caption of an extra image, or None when *rel* is not one of them."""
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
    return None


def caption_line(rel: str, report: Report) -> str:
    """The reference as it appears in the part / assembly Markdown: the path, plus the caption
    for an extra image (the basic images keep their plain reference)."""
    cap = caption_for(rel, report)
    return rel if cap is None else f"{rel}: {cap.what}"
