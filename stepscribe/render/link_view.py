# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Image type 7 (standard, robots): the assembly coloured by link group, with a link legend."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

from stepscribe.models.schema import Report
from stepscribe.render.extra_images import ImageSkipped, _size, _title, swatch_legend
from stepscribe.render.kinematics_view import link_colors, link_labels, recolor_by_link
from stepscribe.render.scene import standard_camera

if TYPE_CHECKING:
    from stepscribe.api import Analysis


def make_assembly(
    analysis: Analysis, report: Report, up: str, front: str, max_side: int
) -> list[tuple[str, Image.Image]]:
    from stepscribe.render import build_scene, render_labelled

    kin = report.understanding.kinematics if report.understanding else None
    if kin is None or not kin.joints:
        raise ImageSkipped("no robot or mechanism with joints was detected")
    items = recolor_by_link(build_scene(analysis), kin)
    w, h = _size(max_side)
    cam = standard_camera("iso", items, up, front, w / h)
    rendered = render_labelled(items, cam, link_labels(kin))  # labels are link IDs
    colors = link_colors(kin)
    entries = [
        (
            (
                round(colors[g.id][0] * 255),
                round(colors[g.id][1] * 255),
                round(colors[g.id][2] * 255),
            ),
            f"{g.id} ground" if g.is_ground else g.id,
        )
        for g in kin.links
    ][:16]
    return [
        ("images/link_map.png", _title(swatch_legend(rendered.image, entries), "link colour map"))
    ]
