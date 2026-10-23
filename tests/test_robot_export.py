"""R5 (first part): robot.json - links, joints, DH-style table, mass estimates, limits from the yaml only."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.pack.robot import build_robot, robot_json

STEEL = 7.85  # g/cm3, the density of the 'steel' keyword


@pytest.fixture(scope="module")
def arm(step_files):  # type: ignore[no-untyped-def]
    opts = AnalyzeOptions(no_timestamp=True, material="steel")
    return analyze_full(step_files["arm_6_axis"], opts).report


def test_a_plain_assembly_has_no_robot_export(analyses) -> None:  # type: ignore[no-untyped-def]
    assert build_robot(analyses("two_plates_assembly").report) is None


def test_the_header_states_units_frame_and_that_it_needs_a_human(arm) -> None:  # type: ignore[no-untyped-def]
    r = build_robot(arm)
    assert r is not None
    assert "needs human verification" in r["status"]
    assert r["units"] == {"length": "mm", "mass": "g", "angle": "deg", "inertia": "g*mm^2"}
    assert "zero" in r["pose_note"] and r["base_link"] == "L0"
    assert len(r["links"]) == 7 and len(r["joints"]) == 6


def test_joints_carry_axis_origin_type_evidence_and_confidence(arm) -> None:  # type: ignore[no-untyped-def]
    r = build_robot(arm)
    assert r is not None
    axes = ["Z", "Y", "Y", "X", "Y", "X"]
    for j, letter in zip(r["joints"], axes, strict=True):
        assert j["type"] == "revolute" and 0 < j["confidence"] <= 1
        assert j["evidence"] and math.isclose(math.hypot(*j["axis"]), 1.0, abs_tol=1e-9)
        assert abs(j["axis"]["XYZ".index(letter)]) > 0.999
    # every origin is on its own axis and relative offsets chain from the parent joint's origin
    j1, j2 = r["joints"][0], r["joints"][1]
    delta = [a - b for a, b in zip(j2["origin_mm"], j1["origin_mm"], strict=True)]
    assert delta == pytest.approx(j2["origin_in_parent_mm"], abs=1e-6)


def test_the_dh_style_table_follows_from_the_axes(arm) -> None:  # type: ignore[no-untyped-def]
    r = build_robot(arm)
    assert r is not None
    rows = r["dh_style"]["rows"]
    assert [abs(round(x["alpha_deg"])) for x in rows] == [0, 90, 0, 90, 90, 90]
    assert rows[1]["a_mm"] == pytest.approx(26.0, abs=1e-6)  # axis 1 (Z) to axis 2 (Y at x=-26)
    assert rows[2]["a_mm"] == pytest.approx(52.0, abs=1e-6)  # the two parallel Y axes
    assert "theta" in r["dh_style"]["note"]


def test_masses_are_labelled_estimates_and_add_up(arm) -> None:  # type: ignore[no-untyped-def]
    r = build_robot(arm)
    assert r is not None
    total = sum(link["mass_g"] for link in r["links"])
    assert total == pytest.approx(sum(p.mass.mass_g for p in arm.parts), rel=1e-9)
    assert all(link["mass_is_estimate"] for link in r["links"])
    assert any("estimate" in w and "density" in w for w in r["warnings"])
    assert any("hollow" in w or "shell" in w for w in r["warnings"])


def test_link_inertia_matches_the_box_formula(arm) -> None:  # type: ignore[no-untyped-def]
    r = build_robot(arm)
    assert r is not None
    base = r["links"][0]  # BASE: a 140 x 80 x 20 mm steel block
    m = 140 * 80 * 20 * 1e-3 * STEEL
    assert base["mass_g"] == pytest.approx(m, rel=1e-6)
    ixx = m / 12 * (80**2 + 20**2)
    iyy = m / 12 * (140**2 + 20**2)
    izz = m / 12 * (140**2 + 80**2)
    inertia = base["inertia_g_mm2"]
    assert (inertia[0][0], inertia[1][1], inertia[2][2]) == pytest.approx((ixx, iyy, izz), rel=1e-4)
    assert base["com_mm"] == pytest.approx([0.0, 0.0, -10.0], abs=1e-6)


def test_limits_are_unknown_unless_the_designer_gave_them(arm) -> None:  # type: ignore[no-untyped-def]
    r = build_robot(arm)
    assert r is not None
    for j in r["joints"]:
        assert j["limits"] == {"lower": None, "upper": None, "unit": "deg", "source": "unknown"}
    u = arm.understanding
    assert u is not None
    u.kinematics.joints[1].range_deg_or_mm = (-90.0, 110.0)
    u.kinematics.joints[1].range_source = "designer"
    u.kinematics.joints[2].range_deg_or_mm = (-10.0, 10.0)
    u.kinematics.joints[2].range_source = "motion_check"  # found by a collision sweep: not a limit
    try:
        r = build_robot(arm)
        assert r is not None
        assert r["joints"][1]["limits"] == {
            "lower": -90.0,
            "upper": 110.0,
            "unit": "deg",
            "source": "design_context.yaml",
        }
        assert r["joints"][2]["limits"]["source"] == "unknown"
    finally:
        for k in (1, 2):
            u.kinematics.joints[k].range_deg_or_mm = None
            u.kinematics.joints[k].range_source = None


def test_the_json_text_is_stable_and_valid(arm) -> None:  # type: ignore[no-untyped-def]
    text = robot_json(arm)
    assert text is not None and text == robot_json(arm)
    assert json.loads(text)["format"] == "stepscribe-robot"


def test_the_pack_contains_robot_json_for_a_robot_only(tmp_path: Path, step_files) -> None:  # type: ignore[no-untyped-def]
    from typer.testing import CliRunner

    from stepscribe.cli import app

    for name, expected in (("arm_6_axis", True), ("two_plates_assembly", False)):
        out = tmp_path / name
        res = CliRunner().invoke(
            app,
            ["pack", str(step_files[name]), "--out", str(out), "--no-images", "--no-timestamp"],
        )
        assert res.exit_code == 0, res.output
        assert bool(list(out.rglob("robot.json"))) is expected


def test_without_a_material_the_masses_are_null_and_the_file_says_why(analyses) -> None:  # type: ignore[no-untyped-def]
    r = build_robot(analyses("arm_6_axis").report)
    assert r is not None
    assert all(link["mass_g"] is None for link in r["links"])
    assert any("No material" in w and "--material" in w for w in r["warnings"])
