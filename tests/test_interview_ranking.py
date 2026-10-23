"""Item 2: for a robot the kinematics questions come first, and answers are written to `kinematics:`."""

from __future__ import annotations

from pathlib import Path

import yaml

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.pack.design_context import apply_context, load_context
from stepscribe.understanding.questions import generate_questions
from stepscribe.understanding.session import Session, save_answers

ROBOT_KINDS = {"kin_base", "joint_axis", "joint_direction", "joint_ranges"}


def test_a_robot_is_asked_about_its_kinematics_before_anything_else(analyses) -> None:  # type: ignore[no-untyped-def]
    report = analyses("arm_6_axis").report
    top = generate_questions(report)
    kinds = [q.kind for q in top]
    assert len(top) == 10 and set(kinds) <= ROBOT_KINDS, kinds
    assert kinds[0] == "kin_base"
    # the joints that rest on a flange alone (the others have a pivot bore that confirms them)
    assert [q.refs[0] for q in top[1:3]] == ["KJ1", "KJ5"]
    assert kinds[1:3] == ["joint_axis"] * 2
    assert kinds[3:9] == ["joint_direction"] * 6  # then the sign of motion, joint by joint
    # then ONE question for the ranges of the whole arm, not six
    assert kinds[9] == "joint_ranges" and top[9].refs == [f"KJ{i}" for i in range(1, 7)]


def test_what_drives_it_and_the_global_questions_come_after_all_of_them(analyses) -> None:  # type: ignore[no-untyped-def]
    every = generate_questions(analyses("arm_6_axis").report, limit=None)
    kinds = [q.kind for q in every]
    last_robot = max(i for i, k in enumerate(kinds) if k in ROBOT_KINDS)
    first_other = min(i for i, k in enumerate(kinds) if k not in ROBOT_KINDS)
    assert first_other > last_robot
    assert (
        kinds.count("joint_ranges") == 1
        and "joint_range" not in kinds
        and kinds.count("joint_direction") == 6
    )
    assert "joint_drive" in kinds[first_other:]
    # the single range question comes after the directions
    assert kinds.index("joint_ranges") > max(
        i for i, k in enumerate(kinds) if k == "joint_direction"
    )


def test_a_design_that_is_not_a_robot_keeps_its_ranking(analyses) -> None:  # type: ignore[no-untyped-def]
    kinds = [q.kind for q in generate_questions(analyses("two_plates_assembly").report)]
    assert not set(kinds) & ROBOT_KINDS


def answered_session(step_files):  # type: ignore[no-untyped-def]
    analysis = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True))
    session = Session(analysis, AnalyzeOptions(no_timestamp=True))
    by = {(q.kind, tuple(q.refs)): q for q in session.all_questions()}
    return session, by


def test_answers_are_written_to_the_kinematics_section(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    session, by = answered_session(step_files)
    session.answer(by[("kin_base", ())].id, "answered", "L0")
    session.answer(by[("joint_axis", ("KJ5",))].id, "answered", "yes")
    session.answer(by[("joint_direction", ("KJ5",))].id, "answered", "cw")
    ranges = by[("joint_ranges", tuple(f"KJ{i}" for i in range(1, 7)))]
    session.answer(ranges.id, "answered", "KJ5: -90 to 110\nKJ2 -30 45")
    path = tmp_path / "design_context.yaml"
    session.save(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    kin = data["kinematics"]
    assert kin["base"] == "BASE"
    rows = {tuple(r["between"]): r for r in kin["joints"]}
    assert set(rows) == {
        ("LINK4", "LINK5"),
        ("LINK1", "LINK2"),
    }  # the one range answer set two joints
    row = rows[("LINK4", "LINK5")]
    assert row["axis"] == "+Y" and row["positive"] == "cw" and row["range"] == [-90.0, 110.0]
    assert rows[("LINK1", "LINK2")]["range"] == [-30.0, 45.0]
    assert set(data["answers"]) >= {by[("joint_direction", ("KJ5",))].id}  # the answers stay too


def test_the_written_section_overrides_detection_on_the_next_run(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    session, by = answered_session(step_files)
    session.answer(by[("joint_axis", ("KJ5",))].id, "answered", "yes")
    session.answer(by[("joint_direction", ("KJ5",))].id, "answered", "cw")
    path = tmp_path / "design_context.yaml"
    session.save(path)
    opts = AnalyzeOptions(no_timestamp=True)
    apply_context(opts, load_context(path))
    report = analyze_full(step_files["arm_6_axis"], opts).report
    u = report.understanding
    assert u is not None
    j = next(j for j in u.kinematics.joints if j.id == "KJ5")
    assert j.declared_by_designer and j.confidence == 1.0 and j.positive_direction == "cw"
    assert any("Confirmed by designer" in e.text for e in j.evidence)
    # the confirmed joint is no longer asked about
    asked = [(q.kind, tuple(q.refs)) for q in generate_questions(report, limit=None)]
    assert ("joint_axis", ("KJ5",)) not in asked and ("joint_direction", ("KJ5",)) not in asked


def test_undoing_an_answer_removes_what_it_wrote(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    session, by = answered_session(step_files)
    qid = by[("joint_direction", ("KJ5",))].id
    session.answer(qid, "answered", "cw")
    path = tmp_path / "design_context.yaml"
    session.save(path)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["kinematics"]["joints"]
    save_answers(path, {}, only=(), remove=[qid])  # what `stepscribe answer --undo` does
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert not (data.get("kinematics") or {}).get("joints")


def test_hand_written_entries_survive_a_save(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "design_context.yaml"
    path.write_text(
        "purpose: demo\nkinematics:\n  joints:\n    - between: [LINK5, LINK6]\n      axis: '+X'\n"
        "      range: [-300, 300]\n",
        encoding="utf-8",
    )
    session, by = answered_session(step_files)
    session.answer(by[("joint_direction", ("KJ5",))].id, "answered", "ccw")
    session.save(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    pairs = {tuple(r["between"]) for r in data["kinematics"]["joints"]}
    assert pairs == {("LINK5", "LINK6"), ("LINK4", "LINK5")} and data["purpose"] == "demo"
    mine = next(r for r in data["kinematics"]["joints"] if r["between"] == ["LINK5", "LINK6"])
    assert mine["range"] == [-300, 300]


def test_the_robot_questions_are_asked_one_round_at_a_time(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    session, by = answered_session(step_files)
    first = session.questions[0]
    assert first.kind == "kin_base"
    session.answer(first.id, "answered", "L0")
    assert session.questions[0].kind == "joint_axis"
    assert Path(tmp_path).exists()


def test_ranges_given_in_the_yaml_are_not_asked_for_again(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "design_context.yaml"
    rows = "".join(
        f"    - between: [{a}, {b}]\n      range: [-100, 100]\n"
        for a, b in (("BASE", "LINK1"), ("LINK1", "LINK2"), ("LINK2", "LINK3"))
    )
    path.write_text("kinematics:\n  joints:\n" + rows, encoding="utf-8")
    opts = AnalyzeOptions(no_timestamp=True)
    apply_context(opts, load_context(path))
    report = analyze_full(step_files["arm_6_axis"], opts).report
    (q,) = [q for q in generate_questions(report, limit=None) if q.kind == "joint_ranges"]
    assert q.refs == ["KJ4", "KJ5", "KJ6"]  # only the joints without a designer range
    done = "".join(
        f"    - between: [{a}, {b}]\n      range: [-100, 100]\n"
        for a, b in (("LINK3", "LINK4"), ("LINK4", "LINK5"), ("LINK5", "LINK6"))
    )
    path.write_text("kinematics:\n  joints:\n" + rows + done, encoding="utf-8")
    opts = AnalyzeOptions(no_timestamp=True)
    apply_context(opts, load_context(path))
    report = analyze_full(step_files["arm_6_axis"], opts).report
    assert not [q for q in generate_questions(report, limit=None) if q.kind == "joint_ranges"]


def synthetic_arm(n: int):  # type: ignore[no-untyped-def]
    """A serial chain of n revolute joints as a KinematicModel (no geometry needed)."""
    import numpy as np

    from stepscribe.geometry.properties import vec3
    from stepscribe.models.schema import Axis, KinematicModel, KinJoint, RigidGroup

    links = [
        RigidGroup(id=f"L{i}", instance_ids=[f"INS{i:03d}"], is_ground=i == 0) for i in range(n + 1)
    ]
    joints = [
        KinJoint(
            id=f"KJ{i + 1}",
            kind="revolute",
            parent_link=f"L{i}",
            child_link=f"L{i + 1}",
            axis=Axis(origin=vec3(np.zeros(3)), direction=vec3(np.array([0.0, 0.0, 1.0]))),
            confidence=0.7,
        )
        for i in range(n)
    ]
    return KinematicModel(
        links=links,
        joints=joints,
        dof=n,
        topology="serial_chain",
        description="",
        mermaid="",
        headline=f"Likely: {n}-axis serial arm (confidence 0.70; evidence x)",
    )


def test_a_robot_needs_at_least_three_joints() -> None:
    """Documented limit (roles.yaml kinematics.arm_headline.robot_min_joints): a two-joint arm is
    asked the ordinary questions; three or more get the robot interview."""
    from stepscribe.understanding.arm_check import is_robot

    assert not is_robot(synthetic_arm(2))
    assert is_robot(synthetic_arm(3))
    assert is_robot(synthetic_arm(6))
    plain = synthetic_arm(4)
    plain.headline = ""
    assert not is_robot(plain)  # no arm headline: not a robot
