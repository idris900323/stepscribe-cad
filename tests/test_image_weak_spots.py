"""Image type 3, the weak-spot overlay."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from image_helpers import fresh, has_color, non_white, pack

from stepscribe.features.holes import edge_distance_segment
from stepscribe.render.extra_images import SEVERITY
from stepscribe.render.overlay import record_text_boxes
from stepscribe.render.weak_spot_view import weak_overlay


def test_a_part_with_a_weak_spot_gets_an_overlay_in_the_severity_colour(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    folder = pack(step_files, tmp_path, "tip_over_cavity", "standard")
    path = folder / "images/parts/PRT001_weak.png"
    assert 0.02 < non_white(path) < 0.98
    assert has_color(path, SEVERITY["high"])
    text = (folder / "images" / "INDEX.md").read_text("utf-8")
    assert "W001 (high, edge_distance, 0.80 mm; refs H001, H002)" in text


def test_a_part_without_weak_spots_has_no_overlay_and_a_note(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = pack(step_files, tmp_path, "plate_4xM3", "standard")
    assert not (folder / "images/parts/PRT001_weak.png").exists()
    index = (folder / "images" / "INDEX.md").read_text("utf-8")
    assert "weak-spot overlay: not drawn for 1 part without weak spots (PRT001)" in index


def test_the_measured_line_has_the_length_of_the_edge_distance(step_files) -> None:  # type: ignore[no-untyped-def]
    ap = fresh(step_files, "tip_over_cavity").parts[0]
    assert ap.part.holes
    for h in ap.part.holes:
        seg = edge_distance_segment(ap.geom, ap.part.holes, h.id)
        assert seg is not None and h.edge_distance_mm is not None
        assert abs(float(np.linalg.norm(seg[0] - seg[1])) - h.edge_distance_mm) < 1e-6


def test_the_overlay_draws_the_value_beside_the_marker(step_files) -> None:  # type: ignore[no-untyped-def]
    analysis = fresh(step_files, "tip_over_cavity")
    ap = analysis.parts[0]
    with record_text_boxes() as texts:
        image = weak_overlay(ap.part, ap.geom, analysis.report, "+Z", "-Y", 1200)
    assert image is not None
    drawn = {t for t, _b, _s in texts}
    assert {"W001 H001", "W001 H002", "0.80 mm", "2.80 mm"} <= drawn
