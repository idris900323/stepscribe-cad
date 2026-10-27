"""Image type 9 (full set): the wall-thickness heat map."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from image_helpers import extras, fresh, has_color, non_white, pack
from PIL import Image

from stepscribe.pack.writer import write_pack
from stepscribe.render.wall_view import THICK, THIN, wall_color, wall_samples


def test_a_thin_walled_part_gets_a_heat_map_in_the_full_set_only(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    full = pack(step_files, tmp_path, "thin_wall_box", "full")
    path = full / "images/parts/PRT001_walls.png"
    assert 0.05 < non_white(path) < 0.99 and max(Image.open(path).size) <= 1200
    assert has_color(path, THIN, tol=10)
    text = (full / "images" / "INDEX.md").read_text("utf-8")
    assert "an estimate" in text and "about 1.20 mm" in text
    assert "images/parts/PRT001_walls.png" not in extras(
        pack(step_files, tmp_path, "thin_wall_box", "standard")
    )


def test_the_samples_are_those_of_the_report(step_files) -> None:  # type: ignore[no-untyped-def]
    ap = fresh(step_files, "thin_wall_box").parts[0]
    d = sorted(t for _p, t in wall_samples(ap.geom))
    assert d and ap.part.min_wall_thickness_mm is not None
    # the report's minimum is the third-smallest sample (a stray ray is not a wall)
    assert d[min(2, len(d) - 1)] == pytest.approx(ap.part.min_wall_thickness_mm, abs=1e-9)
    again = sorted(t for _p, t in wall_samples(ap.geom))
    assert again == d  # same seed, same samples


def test_the_colour_scale_runs_from_red_through_yellow_to_blue() -> None:
    assert wall_color(1.0, 1.0, 5.0) == THIN and wall_color(5.0, 1.0, 5.0) == THICK
    assert wall_color(3.0, 1.0, 5.0) == (240, 210, 40)
    assert wall_color(0.0, 1.0, 5.0) == THIN and wall_color(9.0, 1.0, 5.0) == THICK  # clamped
    assert wall_color(2.0, 2.0, 2.0) == THIN  # no spread: one colour, no division by zero
    green = [wall_color(t, 1.0, 5.0)[1] for t in np.linspace(1, 3, 9)]  # red to yellow
    assert green == sorted(green) and green[0] < green[-1]


def test_without_thickness_data_the_image_is_skipped_with_a_note(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    analysis = fresh(step_files, "thin_wall_box")
    for ap in analysis.parts:
        ap.part.min_wall_thickness_mm = None
    folder = write_pack(analysis, tmp_path, images=True, image_set="full")
    assert "images/parts/PRT001_walls.png" not in extras(folder)
    assert "wall thickness heat map PRT001: not drawn, no wall thickness was sampled" in (
        folder / "images" / "INDEX.md"
    ).read_text("utf-8")
