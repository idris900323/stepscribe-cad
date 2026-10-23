"""Forward kinematics of the URDF reproduces robot.json's link frames."""

from __future__ import annotations

import math

import numpy as np
import pytest
from urdf_fk import descendants, parse_joints, rotation, world_frames

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.pack.robot import build_robot
from stepscribe.pack.urdf import build_urdf


@pytest.fixture(scope="module")
def arm(step_files):  # type: ignore[no-untyped-def]
    report = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True)).report
    robot = build_robot(report)
    assert robot is not None
    return robot, parse_joints(build_urdf(robot))


def test_at_zero_the_urdf_reproduces_the_link_frames_of_robot_json(arm) -> None:  # type: ignore[no-untyped-def]
    robot, joints = arm
    frames = world_frames(joints, robot["base_link"])
    assert np.allclose(frames[robot["base_link"]], np.eye(4))
    for spec in robot["joints"]:
        want = np.array(spec["origin_mm"]) * 1e-3
        got = frames[spec["child"]]
        assert got[:3, 3] == pytest.approx(want, abs=1e-9), spec["id"]
        assert np.allclose(got[:3, :3], np.eye(3))  # link frames are parallel to the file's axes


def test_joint_one_at_ninety_degrees_turns_every_descendant_about_z(arm) -> None:  # type: ignore[no-untyped-def]
    robot, joints = arm
    j1 = robot["joints"][0]
    assert j1["origin_mm"][:2] == pytest.approx(
        [0.0, 0.0]
    )  # the axis passes through the base origin
    zero = world_frames(joints, robot["base_link"])
    turned = world_frames(joints, robot["base_link"], {"joint_KJ1": math.pi / 2})
    rz = rotation(np.array([0.0, 0.0, 1.0]), math.pi / 2)
    moving = descendants(joints, j1["child"])
    assert len(moving) == 6  # every link except the base
    for link in moving:
        assert turned[link][:3, 3] == pytest.approx(rz @ zero[link][:3, 3], abs=1e-9)
        assert np.allclose(turned[link][:3, :3], rz)
    assert np.allclose(turned[robot["base_link"]], np.eye(4))


def test_any_joint_turns_its_descendants_about_its_own_axis(arm) -> None:  # type: ignore[no-untyped-def]
    robot, joints = arm
    zero = world_frames(joints, robot["base_link"])
    for spec in robot["joints"]:
        name = "joint_" + spec["id"]
        turned = world_frames(joints, robot["base_link"], {name: math.radians(30)})
        axis, origin = np.array(spec["axis"]), np.array(spec["origin_mm"]) * 1e-3
        r = rotation(axis, math.radians(30))
        moving = descendants(joints, spec["child"])
        for link in zero:
            if link in moving:
                want = origin + r @ (zero[link][:3, 3] - origin)
                assert turned[link][:3, 3] == pytest.approx(want, abs=1e-9), (spec["id"], link)
            else:
                assert np.allclose(turned[link], zero[link]), (spec["id"], link)


def test_an_irb_style_joint_one_is_in_metres() -> None:
    """Joint 1 at z = 125.7 mm in robot.json is z = 0.1257 m in the URDF."""
    robot = {
        "source": "irb_style",
        "base_link": "L0",
        "warnings": [],
        "dh_style": {"rows": []},
        "links": [
            {"id": "L0", "instances": [{"id": "INS001", "name": "BASE"}], "mass_g": None},
            {"id": "L1", "instances": [{"id": "INS002", "name": "LINK1"}], "mass_g": None},
        ],
        "joints": [
            {
                "id": "KJ1",
                "type": "revolute",
                "parent": "L0",
                "child": "L1",
                "axis": [0.0, 0.0, 1.0],
                "origin_mm": [0.0, 0.0, 125.7],
                "origin_in_parent_mm": [0.0, 0.0, 125.7],
                "limits": {"lower": None, "upper": None, "unit": "deg", "source": "unknown"},
                "positive_direction": None,
                "confidence": 0.55,
            }
        ],
    }
    text = build_urdf(robot)
    assert '<origin xyz="0 0 0.1257" rpy="0 0 0"/>' in text
    (j,) = parse_joints(text)
    assert j.xyz[2] * 1000.0 == pytest.approx(robot["joints"][0]["origin_mm"][2])
    frames = world_frames([j], "L0", {j.name: math.pi / 2})
    assert frames["L1"][:3, 3] == pytest.approx([0.0, 0.0, 0.1257])
