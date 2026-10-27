"""Image type 8b (full set): the joints at the ends of the designer's ranges."""

from __future__ import annotations

from pathlib import Path

from image_helpers import extras, fresh, has_color, non_white
from PIL import Image

from stepscribe.pack.writer import write_pack
from stepscribe.render.range_view import HIGH, LOW


def _with_ranges(step_files):  # type: ignore[no-untyped-def]
    analysis = fresh(step_files, "arm_6_axis")
    kin = analysis.report.understanding.kinematics  # type: ignore[union-attr]
    for j, rng in zip(
        kin.joints[:3], ((-90.0, 90.0), (-45.0, 120.0), (-100.0, 100.0)), strict=True
    ):
        j.range_deg_or_mm, j.range_source = rng, "designer"
    return analysis


def test_the_ranges_image_needs_the_full_set_and_designer_ranges(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    full = write_pack(_with_ranges(step_files), tmp_path / "a", images=True, image_set="full")
    path = full / "images" / "kinematic_ranges.png"
    assert path.is_file() and 0.02 < non_white(path) < 0.99 and max(Image.open(path).size) <= 1200
    assert has_color(path, LOW, tol=40) and has_color(path, HIGH, tol=40)
    line = next(
        x
        for x in (full / "images" / "INDEX.md").read_text("utf-8").splitlines()
        if "kinematic_ranges" in x
    )
    assert "KJ1 -90.0 to 90.0 deg" in line and "KJ2 -45.0 to 120.0 deg" in line
    standard = write_pack(
        _with_ranges(step_files), tmp_path / "b", images=True, image_set="standard"
    )
    assert not (standard / "images" / "kinematic_ranges.png").exists()


def test_without_designer_ranges_it_is_skipped_with_a_note(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = write_pack(fresh(step_files, "arm_6_axis"), tmp_path, images=True, image_set="full")
    assert not (folder / "images" / "kinematic_ranges.png").exists()
    assert "joint range image: not drawn, no joint has a range from the designer" in (
        folder / "images" / "INDEX.md"
    ).read_text("utf-8")
    assert "images/kinematic_diagram.png" not in extras(folder)  # the per-part list only
