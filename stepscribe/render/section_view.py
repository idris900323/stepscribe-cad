# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Image type 5 (full): a section through a part, looking at the cut face."""

from __future__ import annotations

import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt
from OCP.TopoDS import TopoDS_Shape
from PIL import Image

from stepscribe.describe.image_captions import AXIS_LETTERS, has_inner_features, section_plane
from stepscribe.describe.phrases import fmt
from stepscribe.geometry.part_geom import PartGeom
from stepscribe.models.schema import Part, Report
from stepscribe.render.extra_images import ImageSkipped, _size, _title, swatch_legend
from stepscribe.render.raster import render_scene
from stepscribe.render.scene import SceneItem, fit_camera, part_color, scene_bounds
from stepscribe.render.tessellate import tessellate

CUT_COLOR = (214, 39, 40)
DEPTH_TOL = 6e-4


def cut_shape(shape: TopoDS_Shape, lo: np.ndarray, hi: np.ndarray, axis: int, offset: float):  # type: ignore[no-untyped-def]
    """*shape* without the material on the + side of the plane, or None when the cut fails."""
    margin = float(np.linalg.norm(hi - lo)) + 1.0
    start = lo - margin
    size = (hi + margin) - start
    start[axis] = offset
    size[axis] = (hi[axis] + margin) - offset
    box = BRepPrimAPI_MakeBox(gp_Pnt(*map(float, start)), *map(float, size)).Shape()
    op = BRepAlgoAPI_Cut(shape, box)
    if not op.IsDone():
        return None
    result = op.Shape()
    return None if result.IsNull() else result


def section_view(part: Part, geom: PartGeom, up: str, front: str, max_side: int) -> Image.Image:
    if not has_inner_features(part):
        raise ImageSkipped("no holes, cut-outs or pockets to show")
    axis, offset = section_plane(part)
    lo, hi = geom.bounds
    cut = cut_shape(geom.shape, lo, hi, axis, offset)
    if cut is None:
        raise ImageSkipped("the cut failed")
    half = PartGeom(part.id, cut)
    mesh = tessellate(half)
    if len(mesh.triangles) == 0:
        raise ImageSkipped("the cut left nothing to draw")
    item = SceneItem(
        part.id, part.id, part.id, mesh, np.eye(4), part_color(part.id, part.color_rgb)
    )
    w, h = _size(max_side)
    direction = np.zeros(3)
    direction[axis] = 1.0  # the camera sits on the + side and looks at the cut face
    view_up = np.array([0.0, 0.0, 1.0]) if axis != 2 else np.array([0.0, 1.0, 0.0])
    bounds = scene_bounds([item])
    diag = float(np.linalg.norm(bounds[1] - bounds[0])) or 1.0
    cam = fit_camera(0.5 * (bounds[0] + bounds[1]), direction, view_up, bounds, diag, w / h)
    rendered = render_scene([item], cam, (w, h))
    on_plane = 0.5 * (bounds[0] + bounds[1])
    on_plane[axis] = offset
    depth = rendered.project(on_plane)[2]
    mask = (np.abs(rendered.zbuffer - depth) < DEPTH_TOL) & (rendered.zbuffer < 1.0)
    arr = np.array(rendered.image.convert("RGB"))
    arr[mask] = CUT_COLOR
    if not mask.any():
        raise ImageSkipped("the plane does not cut the part")
    image = swatch_legend(Image.fromarray(arr), [(CUT_COLOR, "cut face")])
    letter = AXIS_LETTERS[axis]
    return _title(image, f"{part.id} section {letter} = {fmt(offset, 2)} mm")


def make(
    part: Part,
    geom: PartGeom,
    _report: Report,
    up: str,
    front: str,
    max_side: int,
    _notes: list[str] | None = None,
) -> Image.Image | None:
    return section_view(part, geom, up, front, max_side)
