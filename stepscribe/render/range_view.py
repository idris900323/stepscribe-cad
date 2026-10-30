# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Image type 8b (full, robots with designer ranges): every ranged joint at both ends of its range."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

from stepscribe.models.schema import KinJoint, Report
from stepscribe.render.extra_images import ImageSkipped, _title, swatch_legend
from stepscribe.render.overlay import Label, draw_labels
from stepscribe.render.skeleton_view import (
    _context,
    _draw_bars,
    _faint,
    _vec,
    base_point,
    descendants,
    link_centres,
    pose_bars,
    skeleton_bars,
)

if TYPE_CHECKING:
    from stepscribe.api import Analysis

LOW = (31, 119, 180)  # a joint at the low end of its range
HIGH = (44, 160, 44)  # ... and at the high end


def ranged_joints(report: Report) -> list[KinJoint]:
    kin = report.understanding.kinematics if report.understanding else None
    return [j for j in kin.joints if j.range_deg_or_mm] if kin else []


def make_assembly(
    analysis: Analysis, report: Report, up: str, front: str, max_side: int
) -> list[tuple[str, Image.Image]]:
    """Every joint with a designer range, each at the low and the high end of it (full set)."""
    ranged = [j for j in ranged_joints(report) if j.range_source == "designer"]
    if not ranged:
        raise ImageSkipped("no joint has a range from the designer")
    kin, items, cam, size, _diag = _context(analysis, report, up, front, max_side)
    rendered = _faint(items, cam, size)
    draw = ImageDraw.Draw(rendered.image)
    bars = skeleton_bars(kin, link_centres(kin, items), base_point(kin, items))
    _draw_bars(draw, rendered, bars, (150, 150, 150), width=8)
    labels = []
    for j in ranged:
        assert j.range_deg_or_mm is not None
        lo, hi = j.range_deg_or_mm
        moved = descendants(kin, j.child_link)
        for value, color in ((lo, LOW), (hi, HIGH)):
            _draw_bars(
                draw,
                rendered,
                [b for b in pose_bars(kin, bars, j, value) if b[0] in moved],
                color,
                6,
            )
        x, y, _ = rendered.project(_vec(j.axis.origin))
        labels.append(Label(j.id, x, y))
    image = draw_labels(rendered.image, labels)
    image = swatch_legend(
        image,
        [((150, 150, 150), "zero pose"), (LOW, "low end of range"), (HIGH, "high end of range")],
    )
    return [("images/kinematic_ranges.png", _title(image, "joint ranges"))]
