"""The sign convention: positive = counter-clockwise looking along the axis arrow toward its origin
(right-hand rule). A 'cw' answer flips the axis vector in robot.json and robot.urdf."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner
from urdf_fk import descendants, parse_joints, rotation, world_frames

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.cli import app
from stepscribe.pack.design_context import apply_context, load_context
from stepscribe.pack.robot import build_robot
from stepscribe.pack.urdf import build_urdf
from stepscribe.understanding.answers import AnswerError
from stepscribe.understanding.questions import generate_questions
from stepscribe.understanding.session import Session

JOINTS = [f"KJ{i}" for i in range(1, 7)]


def robot_for(step_files, tmp_path: Path, positive: str | None):  # type: ignore[no-untyped-def]
    """robot.json for the generated arm, with KJ2 (LINK1 to LINK2) given a positive direction."""
    opts = AnalyzeOptions(no_timestamp=True)
    if positive is not None:
        path = tmp_path / f"ctx_{positive}.yaml"
        path.write_text(
            f"kinematics:\n  joints:\n    - between: [LINK1, LINK2]\n      positive: {positive}\n",
            encoding="utf-8",
        )
        apply_context(opts, load_context(path))
    robot = build_robot(analyze_full(step_files["arm_6_axis"], opts).report)
    assert robot is not None
    return robot


def test_the_question_states_the_convention_and_lists_every_axis_arrow(analyses) -> None:  # type: ignore[no-untyped-def]
    (q,) = [
        q
        for q in generate_questions(analyses("arm_6_axis").report, limit=None)
        if q.kind == "joint_directions"
    ]
    assert "counter-clockwise" in q.text and "right-hand rule" in q.text
    assert "looking along the axis arrow toward its origin" in q.text
    for jid, vec in zip(
        JOINTS,
        ("(0, 0, 1)", "(0, 1, 0)", "(0, 1, 0)", "(1, 0, 0)", "(0, 1, 0)", "(1, 0, 0)"),
        strict=True,
    ):
        assert f"{jid} axis arrow {vec}" in q.text, (jid, q.text)


def test_cw_flips_the_axis_in_robot_json_and_the_urdf(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    base = robot_for(step_files, tmp_path, None)["joints"][1]
    flipped_robot = robot_for(step_files, tmp_path, "cw")
    j = flipped_robot["joints"][1]
    assert j["axis"] == pytest.approx([-v for v in base["axis"]]) and j["axis_flipped"] is True
    assert j["positive_direction"] == "cw"
    assert any("Confirmed by designer: flipped" in e for e in j["evidence"])
    urdf = build_urdf(flipped_robot)
    joint = parse_joints(urdf)[1]
    assert joint.axis == pytest.approx(j["axis"])  # the URDF carries the same flipped vector, once
    before_joint = urdf.split('<joint name="joint_KJ2"')[0].rstrip().splitlines()[-1]
    assert "flipped" in before_joint  # the comment that heads the joint block
    others = flipped_robot["joints"]
    assert all(not o["axis_flipped"] for i, o in enumerate(others) if i != 1)


def test_ccw_leaves_the_axis_unchanged(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    base = robot_for(step_files, tmp_path, None)["joints"][1]
    j = robot_for(step_files, tmp_path, "ccw")["joints"][1]
    assert j["axis"] == pytest.approx(base["axis"]) and j["axis_flipped"] is False
    assert any("Confirmed by designer" in e and "counter-clockwise" in e for e in j["evidence"])
    assert not any("flipped" in e for e in j["evidence"])


def test_the_dh_style_numbers_follow_the_flipped_axis(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    base = robot_for(step_files, tmp_path, None)["dh_style"]["rows"]
    flipped = robot_for(step_files, tmp_path, "cw")["dh_style"]["rows"]
    assert (
        flipped[1]["alpha_deg"] != base[1]["alpha_deg"]
        or flipped[2]["alpha_deg"] != base[2]["alpha_deg"]
    )


def test_forward_kinematics_still_agrees_with_a_flipped_joint(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    robot = robot_for(step_files, tmp_path, "cw")
    joints = parse_joints(build_urdf(robot))
    zero = world_frames(joints, robot["base_link"])
    for spec in robot["joints"]:  # the zero pose does not depend on the signs
        assert zero[spec["child"]][:3, 3] == pytest.approx(
            np.array(spec["origin_mm"]) * 1e-3, abs=1e-9
        )
    spec = robot["joints"][1]
    turned = world_frames(joints, robot["base_link"], {"joint_KJ2": math.radians(30)})
    origin, axis = np.array(spec["origin_mm"]) * 1e-3, np.array(spec["axis"])
    r = rotation(axis, math.radians(30))
    original = rotation(-axis, math.radians(-30))  # the same turn seen about the unflipped axis
    assert np.allclose(r, original)
    for link in descendants(joints, spec["child"]):
        want = origin + r @ (zero[link][:3, 3] - origin)
        assert turned[link][:3, 3] == pytest.approx(want, abs=1e-9)


def session_with_question(step_files):  # type: ignore[no-untyped-def]
    analysis = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True))
    session = Session(analysis, AnalyzeOptions(no_timestamp=True))
    (q,) = [q for q in session.all_questions() if q.kind == "joint_directions"]
    return session, q


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("KJ2: sideways", "sideways"),
        ("KJ9: cw", "KJ9"),
        ("KJ2: cw\nKJ3 maybe", "KJ3 maybe"),
        ("   ", "one line per joint"),
        ("left-handed", "left-handed"),
    ],
)
def test_invalid_direction_answers_are_rejected_with_a_clear_message(
    step_files, text, message
) -> None:  # type: ignore[no-untyped-def]
    session, q = session_with_question(step_files)
    with pytest.raises(AnswerError) as err:
        session.answer(q.id, "answered", text)
    assert message in str(err.value) and "KJ1: ccw" in str(err.value)
    assert q.id not in session.answers  # nothing was recorded


def test_a_valid_answer_is_accepted_in_full(step_files) -> None:  # type: ignore[no-untyped-def]
    session, q = session_with_question(step_files)
    session.answer(q.id, "answered", "KJ1: ccw\nKJ2: cw")
    assert session.answers[q.id]["value"] == "KJ1: ccw\nKJ2: cw"


def test_a_bad_range_line_is_rejected_too(step_files) -> None:  # type: ignore[no-untyped-def]
    analysis = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True))
    session = Session(analysis, AnalyzeOptions(no_timestamp=True))
    (q,) = [q for q in session.all_questions() if q.kind == "joint_ranges"]
    with pytest.raises(AnswerError, match="KJ1: lots"):
        session.answer(q.id, "answered", "KJ1: lots")


def test_the_command_line_shows_the_message_and_exits_nonzero(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True))
    (q,) = [
        q
        for q in Session(analysis, AnalyzeOptions(no_timestamp=True)).all_questions()
        if q.kind == "joint_directions"
    ]
    ctx = tmp_path / "design_context.yaml"
    res = CliRunner().invoke(
        app,
        [
            "answer",
            str(step_files["arm_6_axis"]),
            "--id",
            q.id,
            "--value",
            "KJ2: sideways",
            "--context",
            str(ctx),
        ],
    )
    assert res.exit_code == 2, res.output
    assert "sideways" in res.output and "KJ1: ccw" in res.output
    assert not ctx.exists() or "answers" not in ctx.read_text(encoding="utf-8")
