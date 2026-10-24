"""No confident process guess for complex or free-form geometry; ordinary parts keep their guess."""

from __future__ import annotations

import json

import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.pack.design_context import apply_context, load_context
from stepscribe.understanding.process import GEOMETRY, complex_reason

CODE = "complex_geometry"


def reason(faces: int, bspline: int, valid: bool = True) -> str | None:
    return complex_reason(faces=faces, bspline_faces=bspline, valid_solid=valid)


# ---- the rule at its boundaries (limits: process_rules.yaml, section complex_geometry) ------------
def test_the_limits_are_the_documented_ones_and_there_is_no_volume_trigger() -> None:
    assert (GEOMETRY["min_faces"], GEOMETRY["min_freeform_share"]) == (100, 0.15)
    assert set(GEOMETRY) == {"min_faces", "min_freeform_share"}  # no fill / thin-skin limit


def test_an_unclosed_solid_needs_at_least_the_minimum_number_of_faces() -> None:
    assert reason(99, 0, valid=False) is None
    assert reason(100, 0, valid=False) == "100 faces, 0% free-form, not a closed solid"


def test_the_free_form_share_boundary_is_inclusive() -> None:
    assert reason(100, 14) is None
    assert reason(100, 15) == "100 faces, 15% free-form"
    assert reason(99, 60) is None  # a simple part keeps its guess however curved it is


def test_the_reason_states_what_was_measured() -> None:
    assert reason(200, 80, valid=False) == "200 faces, 40% free-form, not a closed solid"


# ---- generated parts through the whole analysis -----------------------------------------------
def top(analysis):  # type: ignore[no-untyped-def]
    part = analysis.report.parts[0]
    assert part.understanding is not None
    return part, part.understanding.process


def test_sculpted_geometry_gets_no_process_guess(analyses) -> None:  # type: ignore[no-untyped-def]
    part, process = top(analyses("freeform_housing"))
    assert part.topology.faces >= 100
    assert part.topology.face_types["bspline"] / part.topology.faces >= 0.15
    (h,) = process.ranked
    assert h.label == "unknown" and h.confidence == 0.0
    assert [e.code for e in h.evidence] == [CODE]
    assert h.evidence[0].text == (
        f"no process guess: complex or free-form geometry ({part.topology.faces} faces, "
        f"{round(100 * part.topology.face_types['bspline'] / part.topology.faces)}% free-form)"
    )


def test_a_complex_part_of_planes_and_cylinders_keeps_its_guess(analyses) -> None:  # type: ignore[no-untyped-def]
    part, process = top(analyses("bossed_plate"))
    assert part.topology.faces >= 100 and part.topology.face_types.get("bspline", 0) == 0
    assert process.ranked[0].label != "unknown" and process.ranked[0].confidence > 0
    assert all(e.code != CODE for h in process.ranked for e in h.evidence)


def test_a_thin_walled_ribbed_housing_keeps_its_guess(analyses) -> None:  # type: ignore[no-untyped-def]
    """100+ planar faces, a valid solid, under 10 % of its bounding box: thin, not a skin."""
    part, process = top(analyses("ribbed_housing"))
    o = part.obb.half_sizes
    assert part.is_valid_solid and part.topology.faces >= 100
    assert part.topology.face_types == {"plane": part.topology.faces}
    assert part.mass.volume_mm3 / (8 * o.x * o.y * o.z) < 0.10
    assert process.ranked[0].label != "unknown" and process.ranked[0].confidence > 0
    assert all(e.code != CODE for h in process.ranked for e in h.evidence)


@pytest.mark.parametrize(
    "name",
    [
        "nema17_plate",
        "plate_4xM3",
        "tube",
        "l_bracket",
        "bolt_circle",
        "cube_10",
        "large_thin_plate",
    ],
)
def test_ordinary_parts_are_untouched(analyses, name) -> None:  # type: ignore[no-untyped-def]
    for p in analyses(name).report.parts:
        assert p.understanding is not None
        assert all(e.code != CODE for h in p.understanding.process.ranked for e in h.evidence), name


def test_the_designers_own_process_still_wins(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    ctx = tmp_path / "design_context.yaml"
    ctx.write_text("parts:\n  freeform_housing:\n    process: cnc milled\n", encoding="utf-8")
    opts = AnalyzeOptions(no_timestamp=True)
    apply_context(opts, load_context(ctx))
    _part, process = top(analyze_full(step_files["freeform_housing"], opts))
    assert process.source == "user" and process.ranked[0].label == "cnc_milled"


# ---- what the outputs say ------------------------------------------------------------------------
def test_no_output_calls_the_part_a_vendor_or_shell_model(analyses) -> None:  # type: ignore[no-untyped-def]
    from stepscribe.describe.part_describer import level1
    from stepscribe.understanding.describe import understanding_markdown

    report = analyses("freeform_housing").report
    texts = [
        json.dumps(report.model_dump(mode="json")),
        report.understanding.summary if report.understanding else "",
        level1(report.parts[0], max_words=400),
        understanding_markdown(report),
    ]
    for text in texts:
        low = text.lower()
        assert "vendor" not in low and "shell model" not in low, text[:200]


def test_the_part_description_says_what_was_measured(analyses) -> None:  # type: ignore[no-untyped-def]
    from stepscribe.describe.part_describer import level1

    text = level1(analyses("freeform_housing").report.parts[0], max_words=400)
    assert "No process guess: complex or free-form geometry (" in text
    assert "injection" not in text.lower() and "3d printed" not in text.lower()


def test_the_process_question_does_not_count_these_parts(analyses) -> None:  # type: ignore[no-untyped-def]
    from stepscribe.understanding.questions import generate_questions

    kinds = [q.kind for q in generate_questions(analyses("freeform_housing").report, limit=None)]
    assert "process" not in kinds


def test_the_summary_says_there_is_no_guess_and_why(analyses) -> None:  # type: ignore[no-untyped-def]
    u = analyses("freeform_housing").report.understanding
    assert u is not None
    low = u.summary.lower()
    assert "injection" not in low and "3d printed" not in low and "fdm" not in low
    assert "no process guess: complex or free-form geometry" in low


# ---- measured facts are still reported, with the generic guideline, labelled as such -------------
def edge_spots(analysis):  # type: ignore[no-untyped-def]
    u = analysis.report.understanding
    assert u is not None
    return [w for w in u.weak_spots if w.category == "edge_distance"]


def test_a_hole_near_the_edge_is_still_reported_on_a_complex_part(analyses) -> None:  # type: ignore[no-untyped-def]
    (spot,) = edge_spots(analyses("freeform_housing"))
    assert spot.value == pytest.approx(1.0, abs=0.01)  # the measured distance
    assert "generic guideline (process unknown)" in spot.message
    assert "1.5 x diameter = 4.5 mm" in spot.message
    assert spot.depends_on_assumption and "generic" in spot.depends_on_assumption


def test_the_same_hole_on_a_part_with_a_known_process_is_not_called_generic(analyses) -> None:  # type: ignore[no-untyped-def]
    (spot,) = edge_spots(analyses("bossed_plate"))
    assert spot.value == pytest.approx(1.0, abs=0.01)
    assert "generic" not in spot.message
    assert "the guideline is" in spot.message


def test_the_minimum_wall_rule_needs_a_process_so_it_stays_quiet(analyses) -> None:  # type: ignore[no-untyped-def]
    """A wall guideline is sourced per process; with none, no wall finding is invented."""
    u = analyses("freeform_housing").report.understanding
    assert u is not None and not [w for w in u.weak_spots if w.category == "thin_wall"]


def test_the_robot_file_uses_the_same_rule_for_its_mass_warning(analyses) -> None:  # type: ignore[no-untyped-def]
    """robot.json's list of bodies whose mass may not be real and the process guess cannot disagree."""
    from stepscribe.pack.robot import _complex_geometry

    assert _complex_geometry(analyses("freeform_housing").report.parts[0])
    assert not _complex_geometry(analyses("bossed_plate").report.parts[0])
    assert not _complex_geometry(analyses("ribbed_housing").report.parts[0])
