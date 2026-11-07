# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Image type 8 (standard, robots): the kinematic diagram, a skeleton of bars and joint axes.

The links are bars, the joints are labelled arrows along their axes (KJ1 ... with the axis
direction), the base is marked, all over a faint outline of the model, in the zero pose of the file.
A second image draws the joint axes as arrows on the shaded model.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw

from stepscribe.describe.phrases import fmt
from stepscribe.models.schema import KinematicModel, KinJoint, Report
from stepscribe.render.extra_images import ImageSkipped, _size, _title, swatch_legend
from stepscribe.render.kinematics_view import ARROW, _head, draw_joint_arrows
from stepscribe.render.overlay import Label, draw_labels
from stepscribe.render.raster import Rendered, render_scene
from stepscribe.render.scene import SceneItem, scene_bounds, standard_camera

if TYPE_CHECKING:
    from stepscribe.api import Analysis

BAR = (20, 90, 110)
ARROW_FRACTION = 0.3  # arrow length as a share of the model diagonal


def _vec(a) -> np.ndarray:  # type: ignore[no-untyped-def]
    return np.array([a.x, a.y, a.z], float)


def link_centres(kin: KinematicModel, items: list[SceneItem]) -> dict[str, np.ndarray]:
    """The middle of the bounding box of every link's instances."""
    by_key = {i.key: i for i in items}
    out: dict[str, np.ndarray] = {}
    for g in kin.links:
        members = [by_key[k] for k in g.instance_ids if k in by_key]
        if members:
            lo, hi = scene_bounds(members)
            out[g.id] = 0.5 * (lo + hi)
    return out


def base_point(kin: KinematicModel, items: list[SceneItem]) -> np.ndarray | None:
    """The foot of the ground link: the middle of the bottom (lowest z) of its bounding box."""
    ground = next((g for g in kin.links if g.is_ground), None)
    if ground is None:
        return None
    by_key = {i.key: i for i in items}
    members = [by_key[k] for k in ground.instance_ids if k in by_key]
    if not members:
        return None
    lo, hi = scene_bounds(members)
    return np.array([0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]), lo[2]])


def skeleton_bars(
    kin: KinematicModel, centres: dict[str, np.ndarray], base: np.ndarray | None
) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """(link ID, start, end) bars. A link runs from the joint that carries it (the base for the
    ground link) to every joint it carries; a link that carries none runs to its own middle."""
    origin_in: dict[str, np.ndarray] = {}
    for j in kin.joints:
        origin_in[j.child_link] = _vec(j.axis.origin)
    bars: list[tuple[str, np.ndarray, np.ndarray]] = []
    for g in kin.links:
        start = origin_in.get(g.id)
        if start is None:
            start = base if base is not None else centres.get(g.id)
        if start is None:
            continue
        outs = [_vec(j.axis.origin) for j in kin.joints if j.parent_link == g.id]
        if not outs and g.id in centres:
            outs = [centres[g.id]]
        bars += [(g.id, start, end) for end in outs if float(np.linalg.norm(end - start)) > 1e-6]
    return bars


def descendants(kin: KinematicModel, link: str) -> set[str]:
    """*link* and every link below it in the chain."""
    found = {link}
    grew = True
    while grew:
        grew = False
        for j in kin.joints:
            if j.parent_link in found and j.child_link not in found:
                found.add(j.child_link)
                grew = True
    return found


def rotate_points(
    points: np.ndarray, origin: np.ndarray, axis: np.ndarray, deg: float
) -> np.ndarray:
    """*points* turned by *deg* degrees about the line through *origin* along *axis* (Rodrigues)."""
    k = axis / np.linalg.norm(axis)
    t = math.radians(deg)
    p = points - origin
    out = p * math.cos(t) + np.cross(k, p) * math.sin(t) + np.outer(p @ k, k) * (1 - math.cos(t))
    return np.asarray(out + origin)


def pose_bars(
    kin: KinematicModel,
    bars: list[tuple[str, np.ndarray, np.ndarray]],
    joint: KinJoint,
    value: float,
) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """The bars with the links below *joint* moved by *value* (degrees, or mm for a slide)."""
    moved = descendants(kin, joint.child_link)
    o, d = _vec(joint.axis.origin), _vec(joint.axis.direction)
    out = []
    for link, a, b in bars:
        if link in moved:
            if joint.kind == "prismatic":
                shift = d / np.linalg.norm(d) * value
                a, b = a + shift, b + shift
            else:
                a, b = rotate_points(np.array([a, b]), o, d, value)
        out.append((link, a, b))
    return out


def _faint(items: list[SceneItem], cam, size: tuple[int, int]) -> Rendered:  # type: ignore[no-untyped-def]
    """The model washed out, so the skeleton on top reads."""
    rendered = render_scene(items, cam, size, highlight=set())
    arr = np.array(rendered.image.convert("RGB")).astype(float)
    rendered.image = Image.fromarray((255 - (255 - arr) * 0.3).astype(np.uint8))
    return rendered


def _draw_bars(
    draw: ImageDraw.ImageDraw,
    rendered: Rendered,
    bars: list[tuple[str, np.ndarray, np.ndarray]],
    color: tuple[int, int, int],
    width: int = 10,
) -> None:
    for _link, a, b in bars:
        xa, ya, _ = rendered.project(a)
        xb, yb, _ = rendered.project(b)
        draw.line([(xa, ya), (xb, yb)], fill=color, width=width)
        for x, y in ((xa, ya), (xb, yb)):
            draw.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=color)


def _context(analysis: Analysis, report: Report, up: str, front: str, max_side: int):  # type: ignore[no-untyped-def]
    from stepscribe.render import build_scene

    kin = report.understanding.kinematics if report.understanding else None
    if kin is None or not kin.joints:
        raise ImageSkipped("no robot or mechanism with joints was detected")
    items = build_scene(analysis)
    w, h = _size(max_side)
    cam = standard_camera("iso", items, up, front, w / h)
    lo, hi = scene_bounds(items)
    return kin, items, cam, (w, h), float(np.linalg.norm(hi - lo)) or 1.0


def diagram(analysis: Analysis, report: Report, up: str, front: str, max_side: int) -> Image.Image:
    kin, items, cam, size, diag = _context(analysis, report, up, front, max_side)
    rendered = _faint(items, cam, size)
    draw = ImageDraw.Draw(rendered.image)
    centres = link_centres(kin, items)
    base = base_point(kin, items)
    _draw_bars(draw, rendered, skeleton_bars(kin, centres, base), BAR)
    length = ARROW_FRACTION * diag
    for j in kin.joints:  # each axis as an arrow with its ID and direction
        o, d = _vec(j.axis.origin), _vec(j.axis.direction)
        d = d / np.linalg.norm(d)
        xa, ya, _ = rendered.project(o - d * length / 2)
        xb, yb, _ = rendered.project(o + d * length / 2)
        draw.line([(xa, ya), (xb, yb)], fill=ARROW, width=5)
        _head(draw, (xa, ya), (xb, yb))
        xo, yo, _ = rendered.project(o)
        draw.ellipse([xo - 9, yo - 9, xo + 9, yo + 9], fill=(255, 255, 255), outline=ARROW, width=4)
    labels = [
        Label(
            f"{j.id} ({', '.join(fmt(c, 2) for c in _vec(j.axis.direction) / np.linalg.norm(_vec(j.axis.direction)))})",
            *rendered.project(_vec(j.axis.origin))[:2],
        )
        for j in kin.joints
    ]
    if base is not None:
        x, y, _ = rendered.project(base)
        draw.rectangle([x - 14, y - 14, x + 14, y + 14], fill=BAR, outline=(0, 0, 0), width=2)
        labels.append(Label("base", x, y))
    image = draw_labels(rendered.image, labels)
    image = swatch_legend(image, [(BAR, "link"), (ARROW, "joint axis")])
    return _title(image, "kinematic diagram, zero pose")


def axes_on_model(
    analysis: Analysis, report: Report, up: str, front: str, max_side: int
) -> Image.Image:
    kin, items, cam, size, diag = _context(analysis, report, up, front, max_side)
    rendered = render_scene(items, cam, size)
    draw_joint_arrows(rendered, kin, diag)
    return _title(rendered.image, "joint axes, zero pose")


def make_assembly(
    analysis: Analysis, report: Report, up: str, front: str, max_side: int
) -> list[tuple[str, Image.Image]]:
    return [
        ("images/kinematic_diagram.png", diagram(analysis, report, up, front, max_side)),
        ("images/kinematic_axes.png", axes_on_model(analysis, report, up, front, max_side)),
    ]
