# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""The extra image types of the ``standard`` and ``full`` image sets.

Every label drawn here is an ID (PRT, H, P, W) or a number; no name from the file reaches a picture.
Each type is built from one function that returns an image, so a failure in one is a one-line note
and the pack is still written.
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw

from stepscribe import limits
from stepscribe.describe.image_captions import (
    KINDS,
    MAX_HOLE_LABELS,
    caption_for,
    hole_label,
    hole_pattern_of,
)
from stepscribe.geometry.part_geom import PartGeom
from stepscribe.models.schema import Hole, Part, Report
from stepscribe.render.overlay import Label, _font, draw_labels, draw_text, save_png, text_size
from stepscribe.render.raster import Rendered, render_scene
from stepscribe.render.scene import (
    CameraSpec,
    SceneItem,
    fit_camera,
    part_color,
    scene_bounds,
    standard_camera,
)
from stepscribe.render.tessellate import tessellate

if TYPE_CHECKING:
    from stepscribe.api import Analysis
    from stepscribe.progress import Tracker

IMAGE_SETS = ("none", "basic", "standard", "full")
DEFAULT_MAX_SIDE = limits.IMAGE_MAX_SIDE
MIN_MAX_SIDE = 400
MAX_PARTS_PER_TYPE = 20  # parts that get a per-part extra image, most important first
MAX_EXTRA_IMAGES = 60  # all extra images of one pack
MAX_FACES = (
    4000  # a part with more faces is skipped (meshing it for five more images is not worth it)
)
CIRCLE_POINTS = 48
THROUGH = (214, 39, 40)
BLIND = (31, 119, 180)
SEVERITY = {
    "high": (214, 39, 40),
    "medium": (255, 127, 14),
    "low": (240, 210, 40),
    "info": (31, 119, 180),
}

# image types of each set, in the order they are rendered (the basic set adds none)
STANDARD_TYPES = ("holes", "views", "weak")
FULL_ONLY_TYPES = ("features", "section")
TYPES = {"standard": STANDARD_TYPES, "full": STANDARD_TYPES + FULL_ONLY_TYPES}
# image types of the whole assembly (robots and assemblies only): module with make_assembly()
STANDARD_ASSEMBLY_TYPES = ("contacts",)
ASSEMBLY_MODULES: dict[str, str] = {"contacts": "stepscribe.render.contact_view"}


def types_for(image_set: str) -> tuple[str, ...]:
    return TYPES.get(image_set, ())


def assembly_types_for(image_set: str) -> tuple[str, ...]:
    return STANDARD_ASSEMBLY_TYPES if image_set in ("standard", "full") else ()


class ImageSkipped(Exception):  # noqa: N818 - not an error: the picture is left out with a reason
    """Raised by an image type that cannot be drawn for a part, with the reason for the index."""


@dataclass
class ExtraResult:
    """What one run of the extra image types produced."""

    files: list[str] = field(default_factory=list)  # paths relative to the pack folder
    assembly_files: list[str] = field(default_factory=list)  # the ones of the whole assembly
    notes: list[str] = field(default_factory=list)  # one line per image type that was skipped


# ------------------------------------------------------------------ projection and label placement
def _unit(h: Hole) -> np.ndarray:
    v = np.array([h.axis.direction.x, h.axis.direction.y, h.axis.direction.z], float)
    return np.asarray(v / np.linalg.norm(v))


def _origin(h: Hole) -> np.ndarray:
    return np.array([h.axis.origin.x, h.axis.origin.y, h.axis.origin.z], float)


def hole_entry_circle(h: Hole, n: int = CIRCLE_POINTS) -> np.ndarray:
    """Points (part frame, mm) on the circle at the hole's entry: the widest of bore, counterbore
    and countersink, in the plane through the entry point perpendicular to the axis."""
    d = _unit(h)
    helper = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    a = np.cross(d, helper)
    a /= np.linalg.norm(a)
    b = np.cross(d, a)
    radius = 0.5 * max(
        h.diameter_mm, h.counterbore_diameter_mm or 0.0, h.countersink_diameter_mm or 0.0
    )
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    circle: np.ndarray = _origin(h) + radius * (np.outer(np.cos(t), a) + np.outer(np.sin(t), b))
    return circle


def project_points(rendered: Rendered, item: SceneItem, pts: np.ndarray) -> np.ndarray:
    """Part-frame points -> pixel (x, y) in *rendered* (the item's own transform applied)."""
    world = pts @ item.matrix[:3, :3].T + item.matrix[:3, 3] + item.offset
    return np.asarray(rendered.project_many(world)[:, :2])


def hole_circle_pixels(rendered: Rendered, item: SceneItem, h: Hole) -> np.ndarray:
    """The projected entry circle of a hole, an (n, 2) polygon in pixels."""
    return project_points(rendered, item, hole_entry_circle(h))


def hole_anchor(rendered: Rendered, item: SceneItem, h: Hole) -> tuple[float, float, float]:
    """Pixel (x, y) and depth of the hole's entry centre: where its label is attached."""
    return rendered.project(item.to_world(_origin(h)))


def point_in_polygon(x: float, y: float, poly: np.ndarray) -> bool:
    """Even-odd test of a point against a polygon given as an (n, 2) array."""
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi, xj, yj = poly[i][0], poly[i][1], poly[j][0], poly[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


# ------------------------------------------------------------------ drawing helpers
def _item(part: Part, geom: PartGeom) -> SceneItem:
    return SceneItem(
        part.id, part.id, part.id, tessellate(geom), np.eye(4), part_color(part.id, part.color_rgb)
    )


def _size(max_side: int) -> tuple[int, int]:
    return max_side, round(max_side * 3 / 4)


def fit_side(image: Image.Image, max_side: int) -> Image.Image:
    """The image scaled down (never up) so that neither side exceeds *max_side* pixels."""
    if max(image.size) <= max_side:
        return image.convert("RGB")
    k = max_side / max(image.size)
    return image.convert("RGB").resize(
        (max(1, round(image.width * k)), max(1, round(image.height * k))), Image.Resampling.LANCZOS
    )


def _title(image: Image.Image, text: str) -> Image.Image:
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    font = _font()
    w, h = text_size(draw, text, font)
    draw.rectangle([8, 8, 8 + w + 16, 8 + h + 12], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    draw_text(draw, (16, 14), text, font)
    return out


def swatch_legend(
    image: Image.Image, entries: list[tuple[tuple[int, int, int], str]]
) -> Image.Image:
    """A colour key in the lower left corner: one swatch and one line of text per entry."""
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    font = _font()
    line_h = 28
    width = max(text_size(draw, t, font)[0] for _c, t in entries) + 56
    top = out.height - 16 - line_h * len(entries)
    draw.rectangle(
        [8, top - 6, 8 + width, out.height - 8], fill=(255, 255, 255), outline=(0, 0, 0), width=2
    )
    for i, (color, text) in enumerate(entries):
        y = top + i * line_h
        draw.rectangle([16, y + 2, 38, y + 22], fill=color, outline=(0, 0, 0), width=1)
        draw_text(draw, (46, y + 2), text, font)
    return out


def axis_camera(item: SceneItem, part: Part, up: str, front: str, aspect: float) -> CameraSpec:
    """Looking down the main hole axis (as the part's 'axis' image does), else the iso view."""
    from stepscribe.assembly.spatial import frame
    from stepscribe.render import dominant_hole_axis

    axis = dominant_hole_axis(part)
    if axis is None:
        return standard_camera("iso", [item], up, front, aspect)
    d = axis[1] / np.linalg.norm(axis[1])
    lo, hi = scene_bounds([item])
    u, _r, _f = frame(up, front)
    view_up = u - d * float(np.dot(u, d))
    if np.linalg.norm(view_up) < 1e-6:
        view_up = np.array([0.0, 1.0, 0.0]) - d * d[1]
    return fit_camera(
        0.5 * (lo + hi),
        -d,
        view_up / np.linalg.norm(view_up),
        (lo, hi),
        float(np.linalg.norm(hi - lo)) or 1.0,
        aspect,
    )


# ------------------------------------------------------------------ 1. hole map
def hole_map(
    part: Part,
    geom: PartGeom,
    up: str,
    front: str,
    max_side: int,
    notes: list[str] | None = None,
) -> Image.Image | None:
    """Looking down the main hole axis, every hole circled and labelled with ID and diameter.
    A hole that faces another way and is hidden from this view is left out and named in *notes*."""
    if not part.holes:
        return None
    w, h = _size(max_side)
    item = _item(part, geom)
    cam = axis_camera(item, part, up, front, w / h)
    rendered = render_scene([item], cam, (w, h))
    draw = ImageDraw.Draw(rendered.image)
    patterns = hole_pattern_of(part)
    labels: list[Label] = []
    hidden: list[str] = []
    view = cam.position - cam.focal
    view = view / np.linalg.norm(view)
    for hole in part.holes[:MAX_HOLE_LABELS]:
        x, y, depth = hole_anchor(rendered, item, hole)
        facing = abs(float(np.dot(_unit(hole), view))) > 0.99  # its entry is seen face on
        if not (facing or rendered.visible(x, y, depth)):
            hidden.append(hole.id)
            continue
        poly = hole_circle_pixels(rendered, item, hole)
        color = THROUGH if hole.is_through else BLIND
        draw.line([*map(tuple, poly), tuple(poly[0])], fill=color, width=4)
        labels.append(Label(hole_label(hole, patterns.get(hole.id)), x, y))
    if hidden and notes is not None:
        shown = ", ".join(hidden[:10]) + (", ..." if len(hidden) > 10 else "")
        noun = "hole faces" if len(hidden) == 1 else "holes face"
        notes.append(
            f"hole map {part.id}: {len(hidden)} {noun} away from this view and not circled ({shown})"
        )
    image = draw_labels(rendered.image, labels)
    image = swatch_legend(image, [(THROUGH, "through hole"), (BLIND, "blind hole")])
    return _title(image, f"{part.id} hole map (dia in mm)")


# ------------------------------------------------------------------ driver
def write_index(
    folder: Path, report: Report, image_set: str, max_side: int, files: list[str], notes: list[str]
) -> None:
    """images/INDEX.md: each extra image, what it shows, the IDs on it and the text it pairs with.
    Only the images this module made are listed (the basic views have their own captions)."""
    lines = [
        "# Image index",
        "",
        f"Image set: {image_set}. Longest side at most {max_side} px. Labels on these images are "
        "IDs (PRT, H, P, W) and numbers only; no names from the file are drawn.",
        "",
        "| File | Shows | IDs on the image | Pairs with |",
        "|---|---|---|---|",
    ]
    for rel in files:
        cap = caption_for(rel, report)
        if cap is None:
            continue
        lines.append(
            f"| {rel.removeprefix('images/')} | {cap.what} | {', '.join(cap.ids)} | {cap.pairs} |"
        )
    if notes:
        lines += ["", "## Not drawn", ""] + [f"- {n}" for n in notes]
    (folder / "images" / "INDEX.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


# the image types that live in a module of their own (the hole map is above); each module has make()
MODULES: dict[str, str] = {
    "views": "stepscribe.render.three_view",
    "weak": "stepscribe.render.weak_spot_view",
    "features": "stepscribe.render.feature_view",
    "section": "stepscribe.render.section_view",
}


def _make(
    kind: str,
    part: Part,
    geom: PartGeom,
    report: Report,
    up: str,
    front: str,
    side: int,
    notes: list[str],
) -> Image.Image | None:
    if kind == "holes":
        return hole_map(part, geom, up, front, side, notes)
    maker = importlib.import_module(MODULES[kind])
    result: Image.Image | None = maker.make(part, geom, report, up, front, side, notes)
    return result


def render_extra_images(
    analysis: Analysis,
    folder: Path,
    image_set: str,
    max_side: int,
    up: str,
    front: str,
    tracker: Tracker | None = None,
) -> ExtraResult:
    """Write the extra images of *image_set* under ``images/parts`` and ``images/INDEX.md``."""
    from stepscribe.describe.budget import rank_parts

    result = ExtraResult()
    kinds = types_for(image_set)
    if not kinds and not assembly_types_for(image_set):
        return result
    report = analysis.report
    by_id = {ap.part.id: ap for ap in analysis.parts}
    out_dir = folder / "images" / "parts"
    out_dir.mkdir(parents=True, exist_ok=True)
    ranked = rank_parts([ap.part for ap in analysis.parts])
    t_last = time.time()
    for kind in kinds:
        done = 0
        empty: list[str] = []
        for part in ranked:
            ap = by_id[part.id]
            if done >= MAX_PARTS_PER_TYPE:
                result.notes.append(
                    f"{KINDS[kind]}: only the {MAX_PARTS_PER_TYPE} most important parts are drawn"
                )
                break
            if len(result.files) >= MAX_EXTRA_IMAGES:
                result.notes.append(f"{KINDS[kind]}: stopped at {MAX_EXTRA_IMAGES} extra images")
                break
            if len(ap.geom.table.faces) > MAX_FACES:
                result.notes.append(
                    f"{KINDS[kind]} {part.id}: not drawn, more than {MAX_FACES} faces"
                )
                continue
            try:
                image = _make(kind, part, ap.geom, report, up, front, max_side, result.notes)
            except ImageSkipped as skip:
                result.notes.append(f"{KINDS[kind]} {part.id}: not drawn, {skip}")
                continue
            except Exception as exc:  # noqa: BLE001 - a picture must never stop the pack
                result.notes.append(f"{KINDS[kind]} {part.id}: not drawn ({type(exc).__name__})")
                continue
            if image is None:
                empty.append(part.id)
                continue
            rel = f"images/parts/{part.id}_{kind}.png"
            save_png(fit_side(image, max_side), str(folder / rel))
            part.images.append(rel)
            result.files.append(rel)
            done += 1
            if tracker is not None:
                now = time.time()
                tracker.image_done(Path(rel).name, now - t_last)
                t_last = now
        if empty:
            what = {
                "weak": "weak spots",
                "features": "features",
                "section": "holes, cut-outs or pockets",
            }.get(kind, "holes")
            shown = ", ".join(empty[:10]) + (", ..." if len(empty) > 10 else "")
            result.notes.append(
                f"{KINDS[kind]}: not drawn for {len(empty)} {'part' if len(empty) == 1 else 'parts'} without {what} ({shown})"
            )
    for kind in assembly_types_for(image_set):
        module = importlib.import_module(ASSEMBLY_MODULES[kind])
        try:
            made: list[tuple[str, Image.Image]] = module.make_assembly(
                analysis, report, up, front, max_side
            )
        except ImageSkipped as skip:
            result.notes.append(f"{KINDS[kind]}: not drawn, {skip}")
            continue
        except Exception as exc:  # noqa: BLE001 - a picture must never stop the pack
            result.notes.append(f"{KINDS[kind]}: not drawn ({type(exc).__name__})")
            continue
        for rel, image in made:
            save_png(fit_side(image, max_side), str(folder / rel))
            result.files.append(rel)
            result.assembly_files.append(rel)
            if tracker is not None:
                now = time.time()
                tracker.image_done(Path(rel).name, now - t_last)
                t_last = now
    write_index(folder, report, image_set, max_side, result.files, result.notes)
    return result
