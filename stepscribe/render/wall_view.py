# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Image type 9 (full): where the sampled wall thickness is thin and where it is thick.

The thickness is the one the analysis reports: rays cast inward from random points of the plane and
cylinder faces, same seed and sample count, so the numbers are those of the report and the picture
is an estimate, never a measurement of every wall.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from stepscribe import config
from stepscribe.describe.phrases import fmt
from stepscribe.geometry.part_geom import PartGeom
from stepscribe.geometry.thickness import _RAY_EPS, _face_samples
from stepscribe.models.schema import Part, Report
from stepscribe.render.extra_images import ImageSkipped, _item, _size, _title
from stepscribe.render.overlay import _font, draw_text, text_size
from stepscribe.render.raster import render_scene
from stepscribe.render.scene import standard_camera

THIN = (214, 39, 40)
MID = (240, 210, 40)
THICK = (31, 119, 180)
MAX_POINTS = 1500


def wall_color(t: float, t_min: float, t_max: float) -> tuple[int, int, int]:
    """Red at the thinnest sample, through yellow, to blue at the thickest."""
    k = 0.0 if t_max <= t_min else min(max((t - t_min) / (t_max - t_min), 0.0), 1.0)
    a, b, u = (THIN, MID, 2 * k) if k < 0.5 else (MID, THICK, 2 * k - 1)
    return (
        round(a[0] + (b[0] - a[0]) * u),
        round(a[1] + (b[1] - a[1]) * u),
        round(a[2] + (b[2] - a[2]) * u),
    )


def wall_samples(
    geom: PartGeom, n_samples: int = config.WALL_SAMPLES
) -> list[tuple[np.ndarray, float]]:
    """(point on the surface, distance through the material) as the analysis samples them."""
    table, mesh = geom.table, geom.trimesh
    cand = [i for i, f in enumerate(table.faces) if f.kind in ("plane", "cylinder") and f.area > 0]
    if not cand or mesh is None:
        return []
    areas = np.array([table.faces[i].area for i in cand])
    per_face = np.maximum(1, np.round(areas / areas.sum() * n_samples)).astype(int)
    rng = np.random.RandomState(config.WALL_SEED)
    out: list[tuple[np.ndarray, float]] = []
    for i, cnt in zip(cand, per_face, strict=True):
        for p, n in _face_samples(geom, i, int(cnt), rng):
            t = mesh.first_hit(p - n * _RAY_EPS, -n)
            if t is not None and t + _RAY_EPS >= config.MIN_FEATURE_SIZE:
                out.append((p, float(t + _RAY_EPS)))
    return out


def wall_heat_map(part: Part, geom: PartGeom, up: str, front: str, max_side: int) -> Image.Image:
    if part.min_wall_thickness_mm is None:
        raise ImageSkipped("no wall thickness was sampled")
    samples = wall_samples(geom)[:MAX_POINTS]
    if not samples:
        raise ImageSkipped("no wall thickness sample could be drawn")
    t_min = min(t for _p, t in samples)
    t_max = max(t for _p, t in samples)
    w, h = _size(max_side)
    item = _item(part, geom)
    cam = standard_camera("iso", [item], up, front, w / h)
    rendered = render_scene([item], cam, (w, h), highlight=set())
    draw = ImageDraw.Draw(rendered.image)
    drawn = 0
    for p, t in sorted(samples, key=lambda s: -s[1]):  # thin ones last, on top
        x, y, depth = rendered.project(item.to_world(p))
        if rendered.visible(x, y, depth):
            draw.ellipse(
                [x - 7, y - 7, x + 7, y + 7], fill=wall_color(t, t_min, t_max), outline=(0, 0, 0)
            )
            drawn += 1
    if not drawn:
        raise ImageSkipped("no sample is visible from the iso view")
    image = _scale_bar(rendered.image, t_min, t_max)
    return _title(image, f"{part.id} wall thickness, estimate (mm)")


def _scale_bar(image: Image.Image, t_min: float, t_max: float) -> Image.Image:
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    font = _font()
    x0, x1, y1 = 16, 316, out.height - 24
    draw.rectangle(
        [8, y1 - 60, x1 + 120, out.height - 8], fill=(255, 255, 255), outline=(0, 0, 0), width=2
    )
    for x in range(x0, x1):
        k = (x - x0) / (x1 - x0)
        draw.line(
            [(x, y1 - 36), (x, y1 - 14)], fill=wall_color(t_min + k * (t_max - t_min), t_min, t_max)
        )
    draw_text(draw, (x0, y1 - 56), f"thin {fmt(t_min, 2)}", font)
    right = f"thick {fmt(t_max, 2)}"
    draw_text(draw, (x1 - text_size(draw, right, font)[0], y1 - 56), right, font)
    return out


def make(
    part: Part,
    geom: PartGeom,
    _report: Report,
    up: str,
    front: str,
    max_side: int,
    _notes: list[str] | None = None,
) -> Image.Image | None:
    return wall_heat_map(part, geom, up, front, max_side)
