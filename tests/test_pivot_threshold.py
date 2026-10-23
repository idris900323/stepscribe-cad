"""The pivot-candidate size rule is configurable and its boundaries are exact."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.assembly.joints import is_pivot_size
from stepscribe.cli import app


def test_the_diameter_boundary_is_inclusive() -> None:
    assert is_pivot_size(20.0, 100.0)  # exactly the minimum
    assert not is_pivot_size(19.99, 100.0)


def test_the_length_boundary_is_inclusive() -> None:
    assert is_pivot_size(30.0, 30.0)  # exactly one diameter long
    assert not is_pivot_size(30.0, 29.99)


def test_the_thresholds_can_be_changed_per_call() -> None:
    assert not is_pivot_size(30.0, 60.0, min_diameter=40.0)
    assert is_pivot_size(30.0, 60.0, min_diameter=25.0)
    assert not is_pivot_size(30.0, 60.0, min_length_ratio=2.5)
    assert is_pivot_size(30.0, 60.0, min_length_ratio=2.0)


def pivots(step_files: dict[str, Path], **options: float) -> int:
    a = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True, **options))
    assert a.report.assembly is not None
    return sum(j.pivot_candidate for j in a.report.assembly.fastener_joints)


def test_the_options_reach_the_joint_detection(step_files: dict[str, Path]) -> None:
    assert pivots(step_files) == 4
    assert pivots(step_files, pivot_min_diameter_mm=31.0) == 0  # the bores are Ø30
    assert pivots(step_files, pivot_min_diameter_mm=30.0) == 4  # exactly Ø30 still counts


def test_the_cli_lists_both_options() -> None:
    env = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}
    out = CliRunner().invoke(app, ["export", "--help"], env=env).output
    assert "--pivot-min-diameter" in out and "--pivot-min-length-ratio" in out
