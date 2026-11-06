"""The axis-view image dimensions the flat of a D-shaped counterbore (IDs only, no part names).

Needs off-screen OpenGL: skipped where it is not available (see ``RENDER_FILES`` in conftest).
"""

from __future__ import annotations

from pathlib import Path

from image_helpers import fresh

from stepscribe.render import render_pack_images
from stepscribe.render.overlay import record_text_boxes


def drawn(step_files: dict[str, Path], tmp_path: Path, name: str) -> tuple[set[str], str]:
    analysis = fresh(step_files, name)
    with record_text_boxes() as log:
        render_pack_images(analysis, tmp_path)
    assert (tmp_path / "images" / "parts" / "PRT001_axis.png").exists()
    return {t for t, _b, _s in log}, analysis.report.parts[0].name


def test_the_axis_view_dimensions_the_flat_beside_the_hole_label(
    step_files: dict[str, Path], tmp_path: Path
) -> None:
    texts, part_name = drawn(step_files, tmp_path, "d_bore_flat")
    assert "3.6 across flats" in texts
    assert "H001 dia 1.3" in texts  # the existing hole label is still drawn
    assert not [t for t in texts if part_name and part_name in t], "IDs only: no part name is drawn"


def test_the_flat_label_does_not_overlap_the_hole_label_or_leave_the_image(
    step_files: dict[str, Path], tmp_path: Path
) -> None:
    analysis = fresh(step_files, "d_bore_flat")
    with record_text_boxes() as log:
        render_pack_images(analysis, tmp_path)
    boxes = {t: (b, s) for t, b, s in log}
    flat_box, size = boxes["3.6 across flats"]
    hole_box, _ = boxes["H001 dia 1.3"]
    assert (
        flat_box[0] >= 0 and flat_box[1] >= 0 and flat_box[2] <= size[0] and flat_box[3] <= size[1]
    )
    apart = (
        flat_box[2] <= hole_box[0]
        or hole_box[2] <= flat_box[0]
        or flat_box[3] <= hole_box[1]
        or hole_box[3] <= flat_box[1]
    )
    assert apart, (flat_box, hole_box)


def test_a_plain_counterbore_gets_no_flat_label(
    step_files: dict[str, Path], tmp_path: Path
) -> None:
    texts, _ = drawn(step_files, tmp_path, "d_bore_round")
    assert "H001 dia 1.3" in texts
    assert not [t for t in texts if "across flats" in t]
