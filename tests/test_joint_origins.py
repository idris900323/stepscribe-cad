"""Item 3: every joint origin lies on its own axis, placed by the previous axis."""

from __future__ import annotations

import numpy as np
import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.geometry.properties import vec3
from stepscribe.models.schema import Axis, KinJoint
from stepscribe.pack.robot import build_robot, joint_frames


def joint(
    i: int, origin: tuple[float, float, float], direction: tuple[float, float, float]
) -> KinJoint:
    return KinJoint(
        id=f"KJ{i}",
        kind="revolute",
        parent_link=f"L{i - 1}",
        child_link=f"L{i}",
        axis=Axis(origin=vec3(np.array(origin)), direction=vec3(np.array(direction))),
        confidence=0.7,
    )


UP = np.array([0.0, 0.0, 1.0])


def origins(*joints: KinJoint) -> list[np.ndarray]:
    return joint_frames(list(joints), "L0", UP)[0]


def test_the_first_joint_keeps_its_detected_point() -> None:
    (o,) = origins(joint(1, (3.0, 4.0, 125.0), (0, 0, 1)))
    assert o == pytest.approx([3.0, 4.0, 125.0])


def test_crossing_axes_meet_at_their_intersection() -> None:
    # axis 1: Z through the file origin; axis 2: X at z=100 (crosses axis 1 at (0,0,100));
    # axis 3: Y with an evidence point 30 mm off the crossing: it must move onto the intersection
    o1, o2, o3 = origins(
        joint(1, (0, 0, 0), (0, 0, 1)),
        joint(2, (40, 0, 100), (1, 0, 0)),
        joint(3, (50, 30, 100), (0, 1, 0)),
    )
    assert o2 == pytest.approx([0.0, 0.0, 100.0])
    assert o3 == pytest.approx([50.0, 0.0, 100.0])  # Y line x=50,z=100 meets X line y=0,z=100


def test_parallel_axes_get_the_previous_origin_projected_onto_the_new_axis() -> None:
    o1, o2 = origins(joint(1, (10, 5, 20), (0, 1, 0)), joint(2, (40, 0, 60), (0, 1, 0)))
    assert o1 == pytest.approx([10, 5, 20])
    assert o2 == pytest.approx([40, 5, 60])  # same y as the previous origin, on the new axis line


def test_a_skew_pair_uses_the_foot_of_the_common_perpendicular() -> None:
    # X through the origin and Y through (30, 0, 50): the closest points are (30,0,0) and (30,0,50)
    o1, o2 = origins(joint(1, (0, 0, 0), (1, 0, 0)), joint(2, (30, 80, 50), (0, 1, 0)))
    assert o2 == pytest.approx([30.0, 0.0, 50.0])


def test_every_origin_is_on_its_axis_and_the_raw_point_is_kept(step_files) -> None:  # type: ignore[no-untyped-def]
    report = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True)).report
    robot = build_robot(report)
    assert robot is not None
    for j in robot["joints"]:
        d = np.array(j["axis"])
        offset = np.array(j["origin_mm"]) - np.array(j["evidence_point_mm"])
        assert np.linalg.norm(np.cross(offset, d)) < 1e-6, j["id"]  # on the axis line
    assert robot["joints"][0]["origin_mm"] == robot["joints"][0]["evidence_point_mm"]
    moved = [j for j in robot["joints"] if j["origin_mm"] != j["evidence_point_mm"]]
    assert moved  # the common-perpendicular rule did move some origins along their axes


def test_the_generated_arm_has_the_expected_parallel_and_skew_origins(step_files) -> None:  # type: ignore[no-untyped-def]
    report = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True)).report
    robot = build_robot(report)
    assert robot is not None
    o = [np.array(j["origin_mm"]) for j in robot["joints"]]
    # joints 2 and 3: parallel Y axes at x=-26 and x=+26, both at z=40
    assert o[2][0] == pytest.approx(26.0) and o[2][2] == pytest.approx(40.0)
    assert o[2][1] == pytest.approx(o[1][1])  # the previous origin projected onto the new axis
    # joints 4 (X at y=160, z=60) and 5 (Y through its flange centroid) are skew: the foot sits on
    # axis 5, at the y of axis 4, and keeps axis 5's own x and z
    evidence5 = np.array(robot["joints"][4]["evidence_point_mm"])
    assert o[4][0] == pytest.approx(90.0)
    assert o[4][2] == pytest.approx(evidence5[2])
    assert o[4][1] == pytest.approx(160.0)
