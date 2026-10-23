"""R6: the designer's `kinematics:` section overrides what was detected, and the interview asks."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.pack.design_context import apply_context, load_context
from stepscribe.understanding import UnderstandingPipeline
from stepscribe.understanding.declared import parse_declared


def finish(step_files, name, context):  # type: ignore[no-untyped-def]
    """Analyse once, then apply a context the way `pack --context` does."""
    opts = AnalyzeOptions(no_timestamp=True)
    apply_context(opts, context)
    a = analyze_full(step_files[name], opts)
    return a.report.understanding


def write(tmp_path: Path, text: str) -> dict:  # type: ignore[type-arg]
    p = tmp_path / "design_context.yaml"
    p.write_text(text, encoding="utf-8")
    return load_context(p)


def test_the_section_is_parsed_with_clear_errors(tmp_path: Path) -> None:
    ctx = write(
        tmp_path,
        """
kinematics:
  base: BASE
  joints:
    - between: [LINK1, LINK2]
      type: revolute
      axis: "+Y"
      range: [-90, 110]
      positive: cw
""",
    )
    decl = parse_declared(ctx)
    assert decl.base == "BASE"
    (j,) = decl.joints
    assert (j.a, j.b, j.kind, j.axis, j.range, j.positive) == (
        "LINK1",
        "LINK2",
        "revolute",
        (0.0, 1.0, 0.0),
        (-90.0, 110.0),
        "cw",
    )
    for bad in ("axis: [0, 0]", "type: swivel", "range: [5]", "positive: sideways"):
        broken = write(
            tmp_path,
            f"kinematics:\n  joints:\n    - between: [A, B]\n      type: revolute\n      axis: '+Z'\n      {bad}\n",
        )
        with pytest.raises(ValueError, match="kinematics"):
            parse_declared(broken)


def test_a_declared_joint_overrides_the_detected_one_and_is_marked(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    ctx = write(
        tmp_path,
        """
kinematics:
  joints:
    - between: [LINK1, LINK2]
      type: revolute
      axis: "+Y"
      range: [-90, 110]
      positive: cw
""",
    )
    u = finish(step_files, "arm_6_axis", ctx)
    assert u is not None
    j = next(j for j in u.kinematics.joints if (j.parent_link, j.child_link) == ("L1", "L2"))
    assert j.declared_by_designer and j.confidence == 1.0
    assert j.range_deg_or_mm == (-90.0, 110.0) and j.positive_direction == "cw"
    assert any(e.code == "designer" and "Confirmed by designer" in e.text for e in j.evidence)
    others = [x for x in u.kinematics.joints if x is not j]
    assert not any(x.declared_by_designer for x in others) and len(others) == 5


def test_a_declared_axis_replaces_the_detected_axis(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    ctx = write(
        tmp_path,
        """
kinematics:
  joints:
    - between: [LINK3, LINK4]
      axis: [0, 1, 0]
""",
    )
    u = finish(step_files, "arm_6_axis", ctx)
    assert u is not None
    j = next(j for j in u.kinematics.joints if (j.parent_link, j.child_link) == ("L3", "L4"))
    d = j.axis.direction
    assert (round(abs(d.x), 3), round(abs(d.y), 3), round(abs(d.z), 3)) == (0.0, 1.0, 0.0)
    assert j.declared_by_designer


def test_a_declared_base_becomes_the_ground_link(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    ctx = write(tmp_path, "kinematics:\n  base: LINK6\n")
    u = finish(step_files, "arm_6_axis", ctx)
    assert u is not None
    ground = [g for g in u.kinematics.links if g.is_ground]
    assert len(ground) == 1 and any(e.code == "designer" for e in ground[0].ground_evidence)
    assert "LINK6" in ground[0].description
    # the chain now runs from LINK6 back to BASE: every joint's parent is nearer the new base
    assert u.kinematics.joints[0].parent_link == ground[0].id


def test_an_unknown_link_name_is_a_warning_not_a_crash(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    ctx = write(
        tmp_path,
        "kinematics:\n  joints:\n    - between: [LINK1, NOSUCHLINK]\n      axis: '+Z'\n",
    )
    opts = AnalyzeOptions(no_timestamp=True)
    apply_context(opts, ctx)
    a = analyze_full(step_files["arm_6_axis"], opts)
    assert any("NOSUCHLINK" in w for w in a.report.warnings)
    assert a.report.understanding is not None


def test_the_interview_asks_for_base_ranges_directions_and_flange_only_axes(analyses) -> None:  # type: ignore[no-untyped-def]
    from stepscribe.understanding.questions import generate_questions

    top = {q.kind for q in generate_questions(analyses("arm_6_axis").report)}
    assert "kin_base" in top  # asked early: it decides how every joint is read
    every = {q.kind for q in generate_questions(analyses("arm_6_axis").report, limit=None)}
    assert {"kin_base", "joint_ranges", "joint_direction", "joint_axis"} <= every
    axis_q = [
        q
        for q in generate_questions(analyses("arm_6_axis").report, limit=None)
        if q.kind == "joint_axis"
    ]
    # only joints whose axis rests on a flange alone are asked about; bore-confirmed ones are not
    assert 0 < len(axis_q) < 6


def test_answers_to_the_new_questions_change_the_model(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    a = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True))
    from stepscribe.understanding.questions import generate_questions

    qs = {(q.kind, tuple(q.refs)): q for q in generate_questions(a.report, limit=None)}
    kj2 = ("joint_direction", ("KJ2",))
    base_q = qs[("kin_base", ())]
    answers = {
        qs[kj2].id: {"status": "answered", "value": "cw"},
        base_q.id: {"status": "answered", "value": "L0"},
    }
    pipeline = UnderstandingPipeline(a, AnalyzeOptions(no_timestamp=True))
    und = pipeline.finish(copy.deepcopy(answers))
    j = next(j for j in und.kinematics.joints if j.id == "KJ2")
    assert j.positive_direction == "cw"
