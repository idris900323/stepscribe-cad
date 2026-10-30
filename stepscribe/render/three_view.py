# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Image type 2: front, top and right views on one sheet, with the overall sizes drawn."""

from __future__ import annotations

import numpy as np  # noqa: F401
from PIL import Image, ImageDraw

from stepscribe.geometry.part_geom import PartGeom
from stepscribe.models.schema import Part, Report
from stepscribe.render.dimensions import INK, annotate, size_caption
from stepscribe.render.extra_images import _item, _size, _title, fit_side
from stepscribe.render.overlay import _font, draw_text
from stepscribe.render.raster import render_scene
from stepscribe.render.scene import scene_bounds, standard_camera


def three_views(
    part: Part,
    geom: PartGeom,
    up: str,
    front: str,
    max_side: int,
) -> Image.Image:
    """Front, top and right orthographic views with the overall sizes drawn, on one sheet."""
    item = _item(part, geom)
    sheet_w, sheet_h = _size(max_side)
    cell_w, cell_h = sheet_w // 2, sheet_h // 2
    bounds = scene_bounds([item])
    sheet = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))
    for k, view in enumerate(("front", "right", "top")):
        # the dimension lines grow the canvas to the right and below; leave room for them
        render_size = (cell_w - 130, cell_h - 80)
        cam = standard_camera(view, [item], up, front, render_size[0] / render_size[1])
        rendered = render_scene([item], cam, render_size)
        annotate(rendered, cam, bounds, None, lines=True)
        tile = _title(fit_side(rendered.image, max(cell_w, cell_h)), view)
        tile.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
        sheet.paste(tile, ((k % 2) * cell_w, (k // 2) * cell_h))
    draw = ImageDraw.Draw(sheet)
    font = _font()
    for i, line in enumerate((f"{part.id}", size_caption(bounds, up, front))):
        draw_text(draw, (cell_w + 20, cell_h + 40 + i * 30), line, font, INK)
    return fit_side(sheet, max_side)


def make(
    part: Part,
    geom: PartGeom,
    _report: Report,
    up: str,
    front: str,
    max_side: int,
    _notes: list[str] | None = None,
) -> Image.Image | None:
    return three_views(part, geom, up, front, max_side)
