# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Image type 4 (full): the features of a part in one colour per family, each with its ID."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from stepscribe.geometry.occ_utils import interior_uv, surface_point
from stepscribe.geometry.part_geom import PartGeom
from stepscribe.models.schema import Part, Report
from stepscribe.render.extra_images import (
    _item,
    _origin,
    _size,
    _title,
    hole_circle_pixels,
    swatch_legend,
)
from stepscribe.render.overlay import Label, draw_labels
from stepscribe.render.raster import render_scene
from stepscribe.render.scene import standard_camera

HOLE = (214, 39, 40)
OPENING = (31, 119, 180)  # cut-outs, slots and pockets
BOSS = (255, 127, 14)
FILLET = (44, 160, 44)
CHAMFER = (148, 103, 189)
MAX_MARKS = 60  # markers on one image
MAX_EDGE_MARKS = 12  # fillets and chamfers are many and small: the first few of each


def _on_face(geom: PartGeom, face_id: str) -> np.ndarray:
    """A point that lies on the face itself (the centroid of a curved face is off its surface)."""
    face = geom.table.by_id(face_id).face
    return np.asarray(surface_point(face, *interior_uv(face)))


def feature_points(part: Part, geom: PartGeom) -> list[tuple[str, str, np.ndarray]]:
    """(family, ID, anchor in the part frame) of every feature that can be placed, in drawing order."""
    out: list[tuple[str, str, np.ndarray]] = []
    out += [("hole", h.id, _origin(h)) for h in part.holes]
    for c in part.cutouts:
        p = c.levels[0].center
        out.append(("opening", c.id, np.array([p.x, p.y, p.z])))
    for s in part.slots:
        if not s.cutout_id:
            out.append(("opening", s.id, np.array([s.center.x, s.center.y, s.center.z])))
    table = geom.table
    for pk in part.pockets:
        if not pk.cutout_id:
            out.append(("opening", pk.id, np.asarray(table.by_id(pk.floor_face_id).centroid)))
    for bo in part.bosses:
        out.append(("boss", bo.id, _on_face(geom, bo.face_ids[0])))
    for fam, items in (
        ("fillet", part.fillets[:MAX_EDGE_MARKS]),
        ("chamfer", part.chamfers[:MAX_EDGE_MARKS]),
    ):
        for f in items:
            out.append((fam, f.id, _on_face(geom, f.face_ids[0])))
    return out[:MAX_MARKS]


COLORS = {"hole": HOLE, "opening": OPENING, "boss": BOSS, "fillet": FILLET, "chamfer": CHAMFER}
NAMES = {
    "hole": "hole",
    "opening": "cut-out, slot or pocket",
    "boss": "boss",
    "fillet": "fillet",
    "chamfer": "chamfer",
}


def feature_highlight(
    part: Part, geom: PartGeom, up: str, front: str, max_side: int, notes: list[str] | None = None
) -> Image.Image | None:
    """An isometric view with a coloured marker and the ID at every feature seen from there."""
    points = feature_points(part, geom)
    if not points:
        return None
    w, h = _size(max_side)
    item = _item(part, geom)
    cam = standard_camera("iso", [item], up, front, w / h)
    rendered = render_scene([item], cam, (w, h))
    draw = ImageDraw.Draw(rendered.image)
    holes = {x.id: x for x in part.holes}
    labels: list[Label] = []
    used: list[str] = []
    hidden: list[str] = []
    for family, fid, p in points:
        x, y, depth = rendered.project(item.to_world(p))
        if not rendered.visible(x, y, depth):
            hidden.append(fid)
            continue
        color = COLORS[family]
        if family == "hole":
            poly = hole_circle_pixels(rendered, item, holes[fid])
            draw.line([*map(tuple, poly), tuple(poly[0])], fill=color, width=4)
        else:
            draw.ellipse([x - 9, y - 9, x + 9, y + 9], fill=color, outline=(0, 0, 0), width=2)
        labels.append(Label(fid, x, y))
        if family not in used:
            used.append(family)
    if not labels:
        if notes is not None:
            notes.append(f"feature highlight {part.id}: no feature is visible from the iso view")
        return None
    if hidden and notes is not None:
        shown = ", ".join(hidden[:10]) + (", ..." if len(hidden) > 10 else "")
        notes.append(
            f"feature highlight {part.id}: {len(hidden)} features are hidden from the iso view ({shown})"
        )
    image = draw_labels(rendered.image, labels)
    image = swatch_legend(image, [(COLORS[f], NAMES[f]) for f in COLORS if f in used])
    return _title(image, f"{part.id} features")


def make(
    part: Part,
    geom: PartGeom,
    _report: Report,
    up: str,
    front: str,
    max_side: int,
    notes: list[str],
) -> Image.Image | None:
    return feature_highlight(part, geom, up, front, max_side, notes)
