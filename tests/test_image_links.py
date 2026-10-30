"""Image type 7 (standard, robots): the link colour map."""

from __future__ import annotations

from pathlib import Path

from image_helpers import fresh, has_color, non_white, pack
from PIL import Image

from stepscribe.render.extra_images import render_extra_images
from stepscribe.render.kinematics_view import LINK_PALETTE
from stepscribe.render.overlay import record_text_boxes


def test_a_robot_gets_the_link_map_and_a_plain_part_does_not(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    arm = pack(step_files, tmp_path, "arm_6_axis", "standard")
    path = arm / "images" / "link_map.png"
    assert path.is_file() and 0.05 < non_white(path) < 0.98 and max(Image.open(path).size) <= 1200
    for color in LINK_PALETTE[1:4]:  # the link colours of the legend are on the image
        assert has_color(path, tuple(round(c * 255) for c in color), tol=40)  # type: ignore[arg-type]
    plate = pack(step_files, tmp_path, "plate_4xM3", "standard")
    assert not (plate / "images" / "link_map.png").exists()
    assert "link colour map: not drawn, no robot or mechanism with joints was detected" in (
        plate / "images" / "INDEX.md"
    ).read_text("utf-8")


def test_the_basic_set_has_no_link_map(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert not (
        pack(step_files, tmp_path, "arm_6_axis", "basic") / "images" / "link_map.png"
    ).exists()


def test_the_labels_are_link_ids_and_the_caption_lists_the_links(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    analysis = fresh(step_files, "arm_6_axis")
    with record_text_boxes() as texts:
        result = render_extra_images(analysis, tmp_path, "standard", 1200, "+Z", "-Y")
    assert "images/link_map.png" in result.files
    drawn = {t for t, _b, _s in texts}
    assert {"L0", "L1", "L6", "L0 ground", "link colour map"} <= drawn
    index = (tmp_path / "images" / "INDEX.md").read_text("utf-8")
    line = next(x for x in index.splitlines() if "| link_map.png |" in x)
    assert "L0 (ground)" in line and "L6" in line and "INS" in line
