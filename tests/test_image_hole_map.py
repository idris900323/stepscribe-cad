"""Image type 1, the hole map: label placement math, colours and the caption."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from image_helpers import fresh, has_color, pack

from stepscribe.render.extra_images import (
    BLIND,
    THROUGH,
    _item,
    axis_camera,
    hole_anchor,
    hole_circle_pixels,
    hole_entry_circle,
    point_in_polygon,
)
from stepscribe.render.raster import render_scene


def test_label_anchors_fall_inside_the_projected_hole_circles(step_files) -> None:  # type: ignore[no-untyped-def]
    ap = fresh(step_files, "plate_4xM3").parts[0]
    item = _item(ap.part, ap.geom)
    cam = axis_camera(item, ap.part, "+Z", "-Y", 4 / 3)
    rendered = render_scene([item], cam, (1200, 900))
    px_per_mm = 900 / (2 * cam.scale)  # orthographic: the visible height is 2 x scale
    assert len(ap.part.holes) == 4
    for hole in ap.part.holes:
        poly = hole_circle_pixels(rendered, item, hole)
        x, y, depth = hole_anchor(rendered, item, hole)
        assert point_in_polygon(x, y, poly), hole.id
        assert rendered.visible(x, y, depth), hole.id
        width = float(poly[:, 0].max() - poly[:, 0].min())
        assert width == pytest.approx(hole.diameter_mm * px_per_mm, rel=0.03), hole.id
        circle = hole_entry_circle(hole)  # in the entry plane, with the hole's radius
        centre = np.array([hole.axis.origin.x, hole.axis.origin.y, hole.axis.origin.z])
        assert np.allclose(np.linalg.norm(circle - centre, axis=1), hole.diameter_mm / 2)


def test_a_point_outside_a_circle_is_not_inside_it() -> None:
    t = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    poly = np.c_[10 * np.cos(t) + 50, 10 * np.sin(t) + 50]
    assert point_in_polygon(50, 50, poly) and point_in_polygon(58, 50, poly)
    assert not point_in_polygon(62, 50, poly) and not point_in_polygon(0, 0, poly)


def test_through_and_blind_holes_have_their_own_colour(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    through = pack(step_files, tmp_path, "plate_4xM3", "standard")
    assert has_color(through / "images/parts/PRT001_holes.png", THROUGH)
    blind = pack(step_files, tmp_path, "blind_holes", "standard")
    assert has_color(blind / "images/parts/PRT001_holes.png", BLIND)


def test_the_caption_names_every_hole_with_its_diameter_and_pattern(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    folder = pack(step_files, tmp_path, "plate_4xM3", "standard")
    text = (folder / "images" / "INDEX.md").read_text("utf-8")
    for hid in ("H001", "H002", "H003", "H004"):
        assert f"{hid} dia 3.4 P001" in text
    assert "Pattern P001: rectangular_grid, 4 holes" in text


def test_every_hole_is_labelled_or_named_in_the_notes(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import re

    from stepscribe.render.extra_images import render_extra_images
    from stepscribe.render.overlay import record_text_boxes

    for name in ("l_bracket", "bearing_block", "blind_holes"):
        analysis = fresh(step_files, name)
        part = analysis.parts[0].part
        with record_text_boxes() as texts:
            result = render_extra_images(analysis, tmp_path / name, "standard", 1200, "+Z", "-Y")
        labelled = {m.group(1) for t, _b, _s in texts if (m := re.match(r"(H\d+) dia ", t))}
        # a hole in a drawn group is covered by the group's legend line
        legend = {m.group(1) for t, _b, _s in texts if (m := re.match(r"(P\d+)  \d+x dia ", t))}
        labelled |= {hid for pat in part.hole_patterns if pat.id in legend for hid in pat.hole_ids}
        noted = set(
            re.findall(r"H\d+", " ".join(n for n in result.notes if n.startswith("hole map")))
        )
        assert {h.id for h in part.holes} <= labelled | noted, name


def test_the_holes_of_a_pattern_are_one_legend_line_not_one_label_each(  # type: ignore[no-untyped-def]
    step_files, tmp_path: Path
) -> None:
    import re

    from stepscribe.render.extra_images import GROUP_MIN_HOLES, render_extra_images
    from stepscribe.render.overlay import record_text_boxes

    analysis = fresh(step_files, "plate_4xM3")
    part = analysis.parts[0].part
    assert part.hole_patterns[0].count >= GROUP_MIN_HOLES
    with record_text_boxes() as texts:
        render_extra_images(analysis, tmp_path / "g", "standard", 1200, "+Z", "-Y")
    drawn = [t for t, _b, _s in texts]
    assert not [t for t in drawn if re.match(r"H\d+ dia ", t)]
    assert any(re.match(r"P001  4x dia 3.4 thru", t) for t in drawn)
