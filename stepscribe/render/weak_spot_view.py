# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Image type 3: the part with its weak spots marked and, for edge distances, the measured line."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from stepscribe.describe.image_captions import part_weak_spots
from stepscribe.describe.phrases import fmt
from stepscribe.features.holes import edge_distance_segment
from stepscribe.geometry.part_geom import PartGeom
from stepscribe.models.schema import Part, Report
from stepscribe.render.extra_images import (
    SEVERITY,
    _item,
    _origin,
    _size,
    _title,
    axis_camera,
    swatch_legend,
)
from stepscribe.render.overlay import Label, _font, draw_labels, draw_text, text_size
from stepscribe.render.raster import render_scene
from stepscribe.render.scene import scene_bounds


# ------------------------------------------------------------------ 3. weak-spot overlay
def _anchor_of(part: Part, ref: str) -> np.ndarray | None:
    """A point (part frame) for a feature ID in a weak spot's refs, or None."""
    for h in part.holes:
        if h.id == ref:
            return _origin(h)
    for c in part.cutouts:
        if c.id == ref:
            p = c.levels[0].center
            return np.array([p.x, p.y, p.z])
    for s in part.slots:
        if s.id == ref:
            return np.array([s.center.x, s.center.y, s.center.z])
    return None


def weak_overlay(
    part: Part,
    geom: PartGeom,
    report: Report,
    up: str,
    front: str,
    max_side: int,
) -> Image.Image | None:
    """The part in grey with its weak spots marked and labelled with their IDs; an edge-distance
    finding also gets the measured line from the hole wall to the nearest edge."""
    spots = part_weak_spots(report, part)
    if not spots:
        return None
    w, h = _size(max_side)
    item = _item(part, geom)
    cam = axis_camera(item, part, up, front, w / h)
    rendered = render_scene([item], cam, (w, h), highlight=set())  # every part in the dim grey
    draw = ImageDraw.Draw(rendered.image)
    centre_px = rendered.project(0.5 * (scene_bounds([item])[0] + scene_bounds([item])[1]))
    labels: list[Label] = []
    used: set[str] = set()
    lines: list[tuple[tuple[float, float], tuple[float, float], str]] = []
    for spot in spots:
        color = SEVERITY[spot.severity]
        used.add(spot.severity)
        found = ((r, _anchor_of(part, r)) for r in spot.refs if r != part.id)
        anchors = [(r, p) for r, p in found if p is not None][:8]
        if not anchors:
            labels.append(Label(spot.id, centre_px[0], centre_px[1]))
            draw.ellipse(
                [centre_px[0] - 12, centre_px[1] - 12, centre_px[0] + 12, centre_px[1] + 12],
                fill=color,
                outline=(0, 0, 0),
                width=2,
            )
        for ref, p in anchors:
            x, y, _d = rendered.project(item.to_world(p))
            draw.ellipse([x - 12, y - 12, x + 12, y + 12], fill=color, outline=(0, 0, 0), width=2)
            labels.append(Label(f"{spot.id} {ref}", x, y))
            hole = next((q for q in part.holes if q.id == ref), None)
            if spot.category == "edge_distance" and hole is not None:
                seg = edge_distance_segment(geom, part.holes, hole.id)
                if seg is not None:
                    a, b = (rendered.project(item.to_world(q)) for q in seg)
                    dist = float(np.linalg.norm(seg[0] - seg[1]))
                    lines.append(((a[0], a[1]), (b[0], b[1]), f"{fmt(dist, 2)} mm"))
    for p0, p1, _text in lines:
        draw.line([p0, p1], fill=(0, 0, 0), width=4)
        for q in (p0, p1):
            draw.ellipse([q[0] - 5, q[1] - 5, q[0] + 5, q[1] + 5], fill=(0, 0, 0))
    font = _font()
    for p0, p1, text in lines:  # values first: the ID labels are then drawn over them
        tw, th = text_size(draw, text, font)
        mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
        draw.rectangle([mx + 6, my - th - 8, mx + 6 + tw + 8, my + 2], fill=(255, 255, 255))
        draw_text(draw, (mx + 10, my - th - 4), text, font)
    image = draw_labels(rendered.image, labels)
    entries: list[tuple[tuple[int, int, int], str]] = [
        (SEVERITY[s], f"{s} severity") for s in ("high", "medium", "low", "info") if s in used
    ]
    if lines:
        entries.append(((0, 0, 0), "measured edge distance"))
    return _title(swatch_legend(image, entries), f"{part.id} weak spots")


def make(
    part: Part, geom: PartGeom, report: Report, up: str, front: str, max_side: int
) -> Image.Image | None:
    return weak_overlay(part, geom, report, up, front, max_side)
