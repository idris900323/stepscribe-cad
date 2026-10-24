# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Do the files of a combined run share one coordinate frame?

Files from one design usually do (each link exported in the assembly's frame).  When they do not,
the parts pile up at the origin or sit far apart.  This only reports; nothing is ever moved.
"""

from __future__ import annotations

from stepscribe.models.schema import AssemblyInfo, BBox

FRAME_WARNING = "do not appear to share a coordinate frame"
NEAR_MM = 3.0  # boxes closer than this count as touching
OVERLAP_SHARE = 0.5  # of the smaller box: this much inside the other is heavy overlap
FILES_SHARE = 0.5  # of the file pairs that overlap heavily before the files are called piled up


def _box(boxes: list[BBox]) -> tuple[list[float], list[float]]:
    lo = [min(getattr(b.min, a) for b in boxes) for a in "xyz"]
    hi = [max(getattr(b.max, a) for b in boxes) for a in "xyz"]
    return lo, hi


def _volume(box: tuple[list[float], list[float]]) -> float:
    return (
        max(0.0, box[1][0] - box[0][0])
        * max(0.0, box[1][1] - box[0][1])
        * max(0.0, box[1][2] - box[0][2])
    )


def _overlap(a: tuple[list[float], list[float]], b: tuple[list[float], list[float]]) -> float:
    lo = [max(a[0][i], b[0][i]) for i in range(3)]
    hi = [min(a[1][i], b[1][i]) for i in range(3)]
    return _volume((lo, hi)) if all(h > low for low, h in zip(lo, hi, strict=True)) else 0.0


def _gap(a: tuple[list[float], list[float]], b: tuple[list[float], list[float]]) -> float:
    d = [max(a[0][i] - b[1][i], b[0][i] - a[1][i], 0.0) for i in range(3)]
    return float(sum(v * v for v in d) ** 0.5)


def check_shared_frame(assembly: AssemblyInfo | None) -> str | None:
    """One sentence when the files look unplaced, else None."""
    if assembly is None:
        return None
    by_file: dict[str, list[BBox]] = {}
    file_of: dict[str, str] = {}
    for inst in assembly.instances:
        if inst.source_file:
            by_file.setdefault(inst.source_file, []).append(inst.global_bbox)
            file_of[inst.id] = inst.source_file
    names = sorted(by_file)
    if len(names) < 2:
        return None
    boxes = {n: _box(by_file[n]) for n in names}
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1 :]]
    heavy = 0
    for a, b in pairs:
        small = min(_volume(boxes[a]), _volume(boxes[b]))
        if small > 0 and _overlap(boxes[a], boxes[b]) / small >= OVERLAP_SHARE:
            heavy += 1
    if heavy / len(pairs) >= FILES_SHARE:
        return (
            f"the {len(names)} files {FRAME_WARNING}: most of them overlap one another, as if "
            "each was exported around its own origin"
        )
    touching = any(
        file_of.get(c.instance_a) != file_of.get(c.instance_b) and c.kind != "near_miss"
        for c in assembly.contacts
        if c.instance_a in file_of and c.instance_b in file_of
    )
    near = any(_gap(boxes[a], boxes[b]) <= NEAR_MM for a, b in pairs)
    if not touching and not near:
        return (
            f"the {len(names)} files {FRAME_WARNING}: no two of them touch or come within "
            f"{NEAR_MM:g} mm of each other"
        )
    return None
