"""Item 1: the kinematic headline carries a confidence and evidence, checks the 6-axis pattern, and
reads the same in 01_overview.md, 05_understanding.md and context_pack.md."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.cli import app
from stepscribe.pack.design_context import apply_context, load_context


def kin(analyses, name):  # type: ignore[no-untyped-def]
    u = analyses(name).report.understanding
    assert u is not None
    return u


def test_a_six_axis_arm_is_headlined_with_confidence_and_evidence(analyses) -> None:  # type: ignore[no-untyped-def]
    u = kin(analyses, "arm_6_axis")
    k = u.kinematics
    assert k.headline.startswith("Likely: 6-axis serial arm (confidence 0.")
    assert "KJ1..KJ6" in k.headline and "L0..L6" in k.headline
    assert k.headline_confidence == 0.70  # capped by the weakest joint (0.55) plus 0.15
    assert u.summary.startswith(k.headline)


def test_the_chain_facts_and_the_pattern_check_are_stated_in_words(analyses) -> None:  # type: ignore[no-untyped-def]
    k = kin(analyses, "arm_6_axis").kinematics
    assert "7 links, 6 revolute joints" in k.statement
    assert (
        "serial order confirmed" in k.statement
        and "L0 -> L1 -> L2 -> L3 -> L4 -> L5 -> L6" in k.statement
    )
    assert len(k.axis_pattern) == 6 and all(line.startswith("OK:") for line in k.axis_pattern)
    assert "matches the usual 6-axis arm layout" in k.statement
    assert k.description.startswith(k.statement)


def write(tmp_path: Path, text: str) -> dict:  # type: ignore[type-arg]
    p = tmp_path / "design_context.yaml"
    p.write_text(text, encoding="utf-8")
    return load_context(p)


def test_a_pattern_mismatch_is_reported_and_lowers_the_confidence(
    step_files, analyses, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    ctx = write(
        tmp_path,
        "kinematics:\n  joints:\n    - between: [LINK4, LINK5]\n      axis: '+X'\n",
    )
    opts = AnalyzeOptions(no_timestamp=True)
    apply_context(opts, ctx)
    u = analyze_full(step_files["arm_6_axis"], opts).report.understanding
    assert u is not None
    k = u.kinematics
    good = kin(analyses, "arm_6_axis").kinematics
    assert k.headline_confidence is not None and good.headline_confidence is not None
    assert k.headline_confidence < good.headline_confidence - 0.05
    assert any(
        line.startswith("DIFFERS:") and "axis 5 is not perpendicular to axis 4" in line
        for line in k.axis_pattern
    )
    assert "differs from the usual 6-axis arm layout" in k.statement
    assert k.headline.startswith(
        "Likely: 6-axis serial arm"
    )  # still an arm, with a lower confidence


def test_named_links_without_joints_are_never_called_static(analyses) -> None:  # type: ignore[no-untyped-def]
    for name in ("named_links_resting", "named_two_links"):
        u = kin(analyses, name)
        text = " ".join([u.summary, u.kinematics.description, u.kinematics.statement])
        assert "static structure" not in text.lower(), name
        assert u.kinematics.headline.startswith("Joint structure not determined"), name
        assert "LINK" in u.kinematics.headline and "no pivot bore" in u.kinematics.headline


def test_unnamed_assemblies_keep_their_existing_wording(analyses) -> None:  # type: ignore[no-untyped-def]
    u = kin(analyses, "two_plates_assembly")
    assert u.summary.startswith("Likely a static structure with no moving joints")
    assert u.kinematics.headline == ""


def test_the_three_outputs_say_the_same_thing(tmp_path: Path, step_files) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "pack"
    res = CliRunner().invoke(
        app,
        ["pack", str(step_files["arm_6_axis"]), "--out", str(out), "--no-images", "--no-timestamp"],
    )
    assert res.exit_code == 0, res.output
    a = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True))
    u = a.report.understanding
    assert u is not None
    statement = u.kinematics.statement
    for name in ("01_overview.md", "05_understanding.md", "context_pack.md"):
        (path,) = list(out.rglob(name))
        assert statement in path.read_text(encoding="utf-8"), name


def strong_context(tmp_path: Path) -> dict:  # type: ignore[type-arg]
    """The designer confirms all six joints (same axes as detected): every joint is at 1.0."""
    rows = ""
    pairs = [
        ("BASE", "LINK1", "+Z"),
        ("LINK1", "LINK2", "+Y"),
        ("LINK2", "LINK3", "+Y"),
        ("LINK3", "LINK4", "+X"),
        ("LINK4", "LINK5", "+Y"),
        ("LINK5", "LINK6", "+X"),
    ]
    for a, b, axis in pairs:
        rows += f"    - between: [{a}, {b}]\n      axis: '{axis}'\n"
    return write(tmp_path, "kinematics:\n  joints:\n" + rows)


def test_the_headline_cannot_be_surer_than_its_weakest_joint(
    step_files, analyses, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    weak = kin(analyses, "arm_6_axis").kinematics
    confs = [j.confidence for j in weak.joints]
    assert min(confs) == 0.55 and max(confs) < 0.8  # flange-only joints at 0.55
    opts = AnalyzeOptions(no_timestamp=True)
    apply_context(opts, strong_context(tmp_path))
    strong = analyze_full(step_files["arm_6_axis"], opts).report.understanding
    assert strong is not None
    assert all(j.confidence == 1.0 for j in strong.kinematics.joints)
    assert (
        weak.headline_confidence is not None and strong.kinematics.headline_confidence is not None
    )
    # both match the 6-axis pattern, but the weak chain is capped at its weakest joint + 0.15
    assert weak.headline_confidence == 0.70
    assert strong.kinematics.headline_confidence - weak.headline_confidence >= 0.15
    assert "capped" in weak.statement and "KJ1" in weak.statement and "0.55" in weak.statement
    assert "capped" not in strong.kinematics.statement


def test_the_cap_applies_to_a_mismatching_pattern_too(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    ctx = write(
        tmp_path, "kinematics:\n  joints:\n    - between: [LINK4, LINK5]\n      axis: '+X'\n"
    )
    opts = AnalyzeOptions(no_timestamp=True)
    apply_context(opts, ctx)
    u = analyze_full(step_files["arm_6_axis"], opts).report.understanding
    assert u is not None and u.kinematics.headline_confidence is not None
    assert (
        u.kinematics.headline_confidence <= 0.65
    )  # capped at 0.70, then 0.08 off for the mismatch
