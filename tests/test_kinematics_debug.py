"""R1: --debug-kinematics explains every contact and every unmatched coaxial hole pair."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full


@pytest.fixture(scope="module")
def debug_of(step_files: dict[str, Path]):  # type: ignore[no-untyped-def]
    cache: dict[str, object] = {}

    def get(name: str):  # type: ignore[no-untyped-def]
        if name not in cache:
            analysis = analyze_full(
                step_files[name], AnalyzeOptions(no_timestamp=True, debug_kinematics=True)
            )
            u = analysis.report.understanding
            assert u is not None and u.kinematics_debug is not None
            cache[name] = u.kinematics_debug
        return cache[name]

    return get


def test_it_is_off_by_default(analyses) -> None:  # type: ignore[no-untyped-def]
    u = analyses("two_plates_assembly").report.understanding
    assert u is not None and u.kinematics_debug is None


def test_a_bolted_pair_is_listed_with_its_geometry_and_the_reason_it_was_merged(debug_of) -> None:  # type: ignore[no-untyped-def]
    dbg = debug_of("two_plates_assembly")
    (c,) = [c for c in dbg.contacts if c.kind == "planar_face"]
    assert c.area_mm2 == pytest.approx(60 * 60 - 4 * 3.14159265 * 1.7**2, abs=0.2)
    assert c.normal is not None and c.normal.z == pytest.approx(1.0, abs=1e-6)
    assert c.centroid is not None and c.centroid.z == pytest.approx(2.5, abs=1e-3)
    assert abs(c.centroid.x) < 0.5 and abs(c.centroid.y) < 0.5
    assert c.distance_mm == pytest.approx(0.0, abs=1e-3)
    assert c.decision == "merged" and c.link_a == c.link_b
    assert "fastener joint J00" in c.reason, c.reason


def test_a_pivot_bore_pair_is_listed_as_not_a_fastener_with_the_reason(debug_of) -> None:  # type: ignore[no-untyped-def]
    dbg = debug_of("pivot_pair_assembly")
    (h,) = dbg.hole_pairs
    assert h.diameters_mm == [50.0, 50.0] and not h.became_fastener
    assert "no standard screw size matches" in h.reason
    assert h.instance_names == ["LINK1", "LINK2"]
    assert h.kinematic_effect  # what the model did with it, in words
    # the flange contact of the same two blocks says why they are one link (or not)
    (c,) = [c for c in dbg.contacts if c.kind == "planar_face"]
    assert c.decision in ("merged", "separate") and c.reason


def test_the_debug_data_is_in_report_json_when_asked(debug_of) -> None:  # type: ignore[no-untyped-def]
    dbg = debug_of("two_plates_assembly")
    data = json.loads(dbg.model_dump_json())
    assert {"contacts", "hole_pairs"} <= set(data)


def test_the_cli_flag_writes_a_readable_file(tmp_path: Path, step_files: dict[str, Path]) -> None:
    from typer.testing import CliRunner

    from stepscribe.cli import app

    out = tmp_path / "o"
    r = CliRunner().invoke(
        app,
        [
            "export",
            str(step_files["pivot_pair_assembly"]),
            "--out",
            str(out),
            "--no-images",
            "--no-zip",
            "--no-timestamp",
            "--debug-kinematics",
        ],
    )
    assert r.exit_code == 0, r.output
    files = list(out.rglob("kinematics_debug.md"))
    assert files, [p.name for p in out.rglob("*")][:20]
    text = files[0].read_text(encoding="utf-8")
    assert "no standard screw size matches" in text and "planar_face" in text
