# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Image type 6 (standard, assemblies): the touching pairs, each named by its contact ID."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from stepscribe.describe.image_captions import selected_contacts
from stepscribe.models.schema import Report
from stepscribe.render.extra_images import ImageSkipped, _size, _title, swatch_legend
from stepscribe.render.overlay import Label, draw_labels
from stepscribe.render.raster import DIM_COLOR, HIGHLIGHT_COLOR, render_scene
from stepscribe.render.scene import standard_camera

if TYPE_CHECKING:
    from stepscribe.api import Analysis


def _rgb(color: tuple[float, float, float]) -> tuple[int, int, int]:
    return (round(color[0] * 255), round(color[1] * 255), round(color[2] * 255))


def contact_anchor(
    lo_a: np.ndarray, hi_a: np.ndarray, lo_b: np.ndarray, hi_b: np.ndarray, tol: float = 1.0
) -> np.ndarray:
    """Where a contact ID is placed: the middle of the overlap of the two parts' bounding boxes
    (grown by *tol* mm, since touching boxes only meet), else midway between their centres."""
    lo = np.maximum(lo_a, lo_b) - tol
    hi = np.minimum(hi_a, hi_b) + tol
    if np.all(hi >= lo):
        return np.asarray(0.5 * (np.maximum(lo_a, lo_b) + np.minimum(hi_a, hi_b)))
    return np.asarray(0.25 * (lo_a + hi_a + lo_b + hi_b))


def make_assembly(
    analysis: Analysis, report: Report, up: str, front: str, max_side: int
) -> list[tuple[str, Image.Image]]:
    from stepscribe.render import build_scene

    if report.assembly is None:
        raise ImageSkipped("a single part has no contacts")
    contacts = selected_contacts(report)
    if not contacts:
        raise ImageSkipped("no contact with a touching face or a fit")
    items = build_scene(analysis)
    by_key = {i.key: i for i in items}
    contacts = [c for c in contacts if c.instance_a in by_key and c.instance_b in by_key]
    if not contacts:
        raise ImageSkipped("the contact parts could not be drawn")
    involved = {k for c in contacts for k in (c.instance_a, c.instance_b)}
    w, h = _size(max_side)
    cam = standard_camera("iso", items, up, front, w / h)
    rendered = render_scene(items, cam, (w, h), highlight=involved)
    labels = []
    for c in contacts:
        a, b = by_key[c.instance_a].bounds(), by_key[c.instance_b].bounds()
        x, y, _d = rendered.project(contact_anchor(a[0], a[1], b[0], b[1]))
        labels.append(Label(c.id, x, y))
    image = draw_labels(rendered.image, labels)
    image = swatch_legend(
        image, [(_rgb(HIGHLIGHT_COLOR), "part in a contact"), (_rgb(DIM_COLOR), "other part")]
    )
    return [("images/contact_map.png", _title(image, "contact map"))]
