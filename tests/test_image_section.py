"""Image type 5 (full set): the section view."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
from image_helpers import extras, fresh, has_color, non_white, pack
from PIL import Image

from stepscribe.describe.image_captions import caption_for, section_plane
from stepscribe.pack.writer import write_pack
from stepscribe.render.overlay import record_text_boxes
from stepscribe.render.section_view import CUT_COLOR


def test_the_section_shows_a_red_cut_face_and_states_the_plane(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = pack(step_files, tmp_path, "tip_over_cavity", "full")
    path = folder / "images/parts/PRT001_section.png"
    assert 0.1 < non_white(path) < 0.99 and max(Image.open(path).size) <= 1200
    assert has_color(path, CUT_COLOR, tol=5)
    index = (folder / "images" / "INDEX.md").read_text("utf-8")
    assert "cut by the plane x = 12.00 mm (part frame)" in index


def test_the_standard_set_has_no_section(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert "images/parts/PRT001_section.png" not in extras(
        pack(step_files, tmp_path, "tip_over_cavity", "standard")
    )


def test_the_plane_runs_along_the_widest_hole_and_across_a_part_without_holes(step_files) -> None:  # type: ignore[no-untyped-def]
    with_hole = fresh(step_files, "tip_over_cavity").parts[0].part
    axis, offset = section_plane(with_hole)
    h = max(with_hole.holes, key=lambda x: (x.diameter_mm, x.id))
    d = [abs(h.axis.direction.x), abs(h.axis.direction.y), abs(h.axis.direction.z)]
    assert d[axis] == min(d)  # the plane is square to a world axis the hole does not run along
    assert offset == pytest.approx([h.axis.origin.x, h.axis.origin.y, h.axis.origin.z][axis])
    cube = fresh(step_files, "cube_10").parts[0].part
    axis, offset = section_plane(cube)
    lo = [cube.bbox.min.x, cube.bbox.min.y, cube.bbox.min.z][axis]
    hi = [cube.bbox.max.x, cube.bbox.max.y, cube.bbox.max.z][axis]
    assert offset == pytest.approx(0.5 * (lo + hi))


def test_a_part_with_nothing_inside_is_skipped_with_a_note(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = pack(step_files, tmp_path, "cube_10", "full")
    assert "images/parts/PRT001_section.png" not in extras(folder)
    index = (folder / "images" / "INDEX.md").read_text("utf-8")
    assert "section view PRT001: not drawn, no holes, cut-outs or pockets to show" in index


def test_a_failed_cut_is_skipped_with_a_note_and_the_pack_is_written(
    step_files, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    import stepscribe.render.section_view as sv

    monkeypatch.setattr(sv, "cut_shape", lambda *_a, **_k: None)
    folder = write_pack(
        fresh(step_files, "tip_over_cavity"), tmp_path, images=True, image_set="full"
    )
    assert "images/parts/PRT001_section.png" not in extras(folder)
    assert "images/parts/PRT001_views.png" in extras(folder)
    assert "section view PRT001: not drawn, the cut failed" in (
        folder / "images" / "INDEX.md"
    ).read_text("utf-8")


def test_the_caption_and_the_title_agree_on_the_plane(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    analysis = fresh(step_files, "tip_over_cavity")
    with record_text_boxes() as texts:
        from stepscribe.render.extra_images import render_extra_images

        result = render_extra_images(analysis, tmp_path, "full", 1200, "+Z", "-Y")
    cap = caption_for("images/parts/PRT001_section.png", analysis.report)
    assert cap is not None and "images/parts/PRT001_section.png" in result.files
    title = next(t for t, _b, _s in texts if "section" in t)
    assert re.search(r"section ([xyz]) = ([\d.]+) mm", title)
    m = re.search(r"section ([xyz]) = ([\d.]+) mm", title)
    assert m is not None and f"plane {m.group(1)} = {m.group(2)} mm" in cap.what
    assert np.isfinite(float(m.group(2)))
