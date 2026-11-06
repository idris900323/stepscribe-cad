"""A counterbore with a flat (a D-shaped bore): described, measured, and never its own nearest edge.

The numbers are worked out by hand in ``fixtures/flat_fixtures.py``: across flats 1.5 + 2.1 = 3.6, flat
chord 2 x sqrt(2.1^2 - 1.5^2) = 2.94, flat depth 8.6, hole wall to the flat 1.5 - 0.65 = 0.85, hole wall to
the round counterbore wall opposite 2.1 - 0.65 = 1.45.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from image_helpers import fresh

from stepscribe.describe.phrases import fmt, hole_callout
from stepscribe.render import render_pack_images
from stepscribe.render.features import hole_text, panel_lines
from stepscribe.render.overlay import record_text_boxes

PHRASE = "with a flat (3.6 across flats, flat 1.5 from the axis)"


def hole(analyses, name: str):  # type: ignore[no-untyped-def]
    (h,) = analyses(name).report.parts[0].holes
    return h


# ---------------------------------------------------------------- the flat is found and measured
def test_the_flat_is_measured_to_the_hand_worked_numbers(analyses) -> None:  # type: ignore[no-untyped-def]
    h = hole(analyses, "d_bore_flat")
    assert h.entry_type == "counterbore"
    assert h.diameter_mm == pytest.approx(1.3) and h.is_through
    assert h.counterbore_diameter_mm == pytest.approx(4.2)
    assert h.counterbore_depth_mm == pytest.approx(8.6)
    f = h.counterbore_flat
    assert f is not None and len(f.face_ids) == 1
    assert f.distance_from_axis_mm == pytest.approx(1.5, abs=1e-3)
    assert f.across_flats_mm == pytest.approx(3.6, abs=1e-3)
    assert f.chord_length_mm == pytest.approx(2.94, abs=5e-3)
    assert f.depth_mm == pytest.approx(8.6, abs=1e-3)
    assert f.hole_wall_to_flat_mm == pytest.approx(0.85, abs=1e-3)
    assert f.hole_wall_to_round_wall_mm == pytest.approx(1.45, abs=1e-3)
    assert (f.normal.x, f.normal.y, f.normal.z) == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)


def test_the_flat_face_is_the_one_plane_parallel_to_the_axis(analyses) -> None:  # type: ignore[no-untyped-def]
    part = analyses("d_bore_flat").report.parts[0]
    f = part.holes[0].counterbore_flat
    assert f is not None
    assert part.topology.face_types["plane"] == 4  # top, bottom, bore floor and the flat


# ---------------------------------------------------------------- a plain round counterbore is as before
def test_a_plain_round_counterbore_has_no_flat_and_keeps_its_numbers(analyses) -> None:  # type: ignore[no-untyped-def]
    h = hole(analyses, "d_bore_round")
    assert h.counterbore_flat is None
    assert h.counterbore_diameter_mm == pytest.approx(4.2)
    assert h.counterbore_depth_mm == pytest.approx(8.6)
    # the wall left is the Ø8 shaft round the Ø4.2 counterbore: 4.0 - 2.1, as before the change
    assert h.edge_distance_mm == pytest.approx(1.9, abs=1e-3)
    assert hole_callout(h) == "Ø1.3 THRU ⌴ Ø4.2 ↧ 8.6"
    assert hole_text(h, with_id=False) == "dia 1.3 thru, cbore dia 4.2 x 8.6"


def test_report_json_carries_the_flat_only_where_there_is_one(analyses) -> None:  # type: ignore[no-untyped-def]
    flat = json.loads(analyses("d_bore_flat").report.model_dump_json())["parts"][0]["holes"][0]
    plain = json.loads(analyses("d_bore_round").report.model_dump_json())["parts"][0]["holes"][0]
    assert "counterbore_flat" in flat and flat["counterbore_flat"][
        "across_flats_mm"
    ] == pytest.approx(3.6)
    assert "counterbore_flat" not in plain


def test_a_ledge_over_part_of_the_depth_is_not_a_flat(analyses) -> None:  # type: ignore[no-untyped-def]
    """The plane is 1.5 mm from the axis and cuts the right chord, but runs 3 mm of the 8.6 mm depth."""
    h = hole(analyses, "d_bore_flat_short")
    assert h.counterbore_flat is None
    assert h.counterbore_diameter_mm == pytest.approx(4.2)
    assert "with a flat" not in hole_text(h, with_id=False)


def test_rounded_corners_still_leave_a_flat(analyses) -> None:  # type: ignore[no-untyped-def]
    """Rounding the flat's two corners shortens its face (2.94 mm chord to about 2.3 mm); it is still the
    flat of a D bore, with the same across-flats value."""
    f = hole(analyses, "d_bore_flat_corners").counterbore_flat
    assert f is not None
    assert f.across_flats_mm == pytest.approx(3.6, abs=1e-3)
    assert f.chord_length_mm < 2.9  # the corners took some of it
    # the rounded corners are the counterbore's own: the nearest edge is still the flat
    assert hole(analyses, "d_bore_flat_corners").edge_distance_mm == pytest.approx(0.85, abs=1e-3)


def test_no_other_fixture_gets_a_flat(analyses) -> None:  # type: ignore[no-untyped-def]
    for name in ("cbore", "csk", "plate_4xM3", "blind_holes", "bearing_block"):
        for part in analyses(name).report.parts:
            assert all(h.counterbore_flat is None for h in part.holes), name


# ---------------------------------------------------------------- the nearest edge
def test_the_nearest_edge_of_a_hole_in_the_floor_is_the_flat(analyses) -> None:  # type: ignore[no-untyped-def]
    """0.85 mm: the hole wall to the flat. The round counterbore wall (1.45 mm) and the part's own
    outer wall (1.9 mm from the counterbore) are further."""
    assert hole(analyses, "d_bore_flat").edge_distance_mm == pytest.approx(0.85, abs=1e-3)


def test_a_rounded_mouth_does_not_make_the_edge_distance_zero(analyses) -> None:  # type: ignore[no-untyped-def]
    """A 0.4 mm fillet round the bore's mouth ends in a corner that touches the bore's own wall at one
    vertex. That corner, the fillet and the entry face behind it belong to the hole's own mouth: the
    edge distance used to read 0.0 here, and must not read 0.4 (the fillet) either."""
    h = hole(analyses, "d_bore_flat_rounded")
    assert h.edge_distance_mm == pytest.approx(0.85, abs=1e-3)
    assert h.counterbore_flat is not None
    assert h.counterbore_flat.across_flats_mm == pytest.approx(3.6, abs=1e-3)


def test_the_panel_line_shows_the_measured_distance_not_zero(analyses) -> None:  # type: ignore[no-untyped-def]
    part = analyses("d_bore_flat").report.parts[0]
    (line,) = [x for x in panel_lines(part) if x.startswith("Nearest hole to an edge")]
    assert line == f"Nearest hole to an edge: {fmt(part.holes[0].edge_distance_mm or 0.0)} mm"
    assert line != "Nearest hole to an edge: 0.0 mm"


# ---------------------------------------------------------------- text
def test_a_bore_with_a_flat_is_described_as_such(analyses) -> None:  # type: ignore[no-untyped-def]
    h = hole(analyses, "d_bore_flat")
    assert hole_text(h, with_id=False) == f"dia 1.3 thru, cbore dia 4.2 x 8.6 {PHRASE}"
    assert hole_callout(h) == f"Ø1.3 THRU ⌴ Ø4.2 ↧ 8.6 {PHRASE}"


def test_the_pack_text_names_the_flat(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from stepscribe.pack.writer import write_pack

    folder = write_pack(fresh(step_files, "d_bore_flat"), tmp_path / "pack", images=False)
    text = "\n".join(p.read_text("utf-8") for p in sorted(folder.rglob("*.md")))
    assert PHRASE in text


# ---------------------------------------------------------------- the axis-view image
def drawn(step_files, tmp_path: Path, name: str) -> tuple[set[str], str]:  # type: ignore[no-untyped-def]
    analysis = fresh(step_files, name)
    with record_text_boxes() as log:
        render_pack_images(analysis, tmp_path)
    assert (tmp_path / "images" / "parts" / "PRT001_axis.png").exists()
    return {t for t, _b, _s in log}, analysis.report.parts[0].name


def test_the_axis_view_dimensions_the_flat_beside_the_hole_label(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    texts, part_name = drawn(step_files, tmp_path, "d_bore_flat")
    assert "3.6 across flats" in texts
    assert "H001 dia 1.3" in texts  # the existing hole label is still drawn
    assert not [t for t in texts if part_name and part_name in t], "IDs only: no part name is drawn"


def test_the_flat_label_does_not_overlap_the_hole_label_or_leave_the_image(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
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


def test_a_plain_counterbore_gets_no_flat_label(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    texts, _ = drawn(step_files, tmp_path, "d_bore_round")
    assert "H001 dia 1.3" in texts
    assert not [t for t in texts if "across flats" in t]
