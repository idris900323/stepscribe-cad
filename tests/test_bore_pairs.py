"""An unmatched coaxial stack at or above the minimum diameter is never a fastener joint.

Long enough: a pivot candidate. Too short: a large coaxial bore pair (a locating feature or a bearing
seat), listed in its own pack section and left out of relations, load paths, the shopping list and
the fastener counts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.assembly.joints import stack_kind
from stepscribe.cli import app

WORDS = re.compile(r"bolt|fasten|screw|\bnut\b", re.I)


# ---- the rule, as a function (limits: roles.yaml kinematics.pivot, or the command-line options) --
@pytest.mark.parametrize(
    ("diameter", "length", "kind"),
    [
        (50.0, 60.0, "pivot"),  # long enough
        (50.0, 50.0, "pivot"),  # exactly one diameter long is long enough
        (50.0, 49.99, "bore_pair"),  # just too short
        (50.0, 20.0, "bore_pair"),
        (20.0, 100.0, "pivot"),  # exactly the minimum diameter
        (19.99, 100.0, None),  # below it: an ordinary unmatched stack, not touched
        (19.99, 5.0, None),
        (20.0, 5.0, "bore_pair"),
    ],
)
def test_the_stack_kind_boundaries(diameter: float, length: float, kind: str | None) -> None:
    assert stack_kind(diameter, length) == kind


def test_the_limits_can_be_changed() -> None:
    assert stack_kind(30.0, 40.0, min_diameter=31.0) is None
    assert stack_kind(30.0, 40.0, min_diameter=30.0) == "pivot"
    assert stack_kind(30.0, 40.0, min_length_ratio=1.5) == "bore_pair"


# ---- generated pairs through the whole analysis ---------------------------------------------------
def asm(analyses, name):  # type: ignore[no-untyped-def]
    report = analyses(name).report
    assert report.assembly is not None and report.understanding is not None
    return report, report.assembly


def test_a_20_mm_pair_of_d50_is_a_bore_pair_not_a_fastener_and_not_a_pivot(analyses) -> None:  # type: ignore[no-untyped-def]
    _r, a = asm(analyses, "bore_pair_assembly")
    (j,) = a.fastener_joints
    assert j.common_diameter_mm == pytest.approx(50.0) and j.stack_thickness_mm == pytest.approx(
        20.0
    )
    assert j.bore_pair and not j.pivot_candidate and j.suggested_fastener is None
    assert j.confidence > 0
    assert "locating feature or bearing seat" in j.evidence
    assert a.fasteners == [] and a.pivots == [] and a.bore_pairs == [j]


def test_the_same_pair_60_mm_deep_is_a_pivot(analyses) -> None:  # type: ignore[no-untyped-def]
    _r, a = asm(analyses, "pivot_pair_assembly")
    (j,) = a.fastener_joints
    assert j.pivot_candidate and not j.bore_pair
    assert a.fasteners == [] and a.bore_pairs == [] and a.pivots == [j]


def test_a_real_bolted_pair_is_still_a_fastener(analyses) -> None:  # type: ignore[no-untyped-def]
    _r, a = asm(analyses, "two_plates_assembly")
    assert len(a.fasteners) == 4 and a.pivots == [] and a.bore_pairs == []
    assert all(not j.pivot_candidate and not j.bore_pair for j in a.fastener_joints)
    assert any(rel.predicate == "bolted_to" for rel in a.relations)


def test_the_minimum_diameter_decides_it_on_real_geometry(step_files) -> None:  # type: ignore[no-untyped-def]
    """The same Ø50 recess pair: a bore pair at a 50 mm minimum (inclusive), an ordinary stack above."""

    def kinds(minimum: float) -> tuple[bool, bool]:
        opts = AnalyzeOptions(no_timestamp=True, pivot_min_diameter_mm=minimum)
        a = analyze_full(step_files["bore_pair_assembly"], opts).report.assembly
        assert a is not None
        (j,) = a.fastener_joints
        return j.bore_pair, j.pivot_candidate

    assert kinds(50.0) == (True, False)
    assert kinds(50.01) == (False, False)  # below the minimum: left as an unmatched stack


def test_a_bore_pair_is_not_a_bolted_relation_a_shopping_item_or_a_load_edge(analyses) -> None:  # type: ignore[no-untyped-def]
    report, a = asm(analyses, "bore_pair_assembly")
    assert a.fastener_shopping_list == []
    for rel in a.relations:
        assert rel.predicate != "bolted_to" and not WORDS.search(rel.sentence), rel.sentence
    u = report.understanding
    assert u is not None
    assert not re.search(r"bolt|screw|fastener pieces|to buy", u.summary, re.I), u.summary
    load = json.dumps([p.model_dump(mode="json") for p in u.load_paths])
    assert "fastened" not in load and not WORDS.search(load), load[:300]
    for w in u.weak_spots:
        assert w.category not in ("single_fastener", "cantilever", "short_screw"), w
        assert not WORDS.search(w.message), w.message


def test_a_bore_pair_does_not_lock_the_parts_together_as_a_clamp(step_files) -> None:  # type: ignore[no-untyped-def]
    opts = AnalyzeOptions(no_timestamp=True, debug_kinematics=True)
    u = analyze_full(step_files["bore_pair_assembly"], opts).report.understanding
    assert u is not None and u.kinematics_debug is not None
    assert all("clamped by fastener joint" not in c.reason for c in u.kinematics_debug.contacts)
    (pair,) = u.kinematics_debug.hole_pairs
    assert "fixed" not in pair.kinematic_effect and "clamp" not in pair.kinematic_effect
    assert "soft connection" in pair.kinematic_effect  # only the planar rest at their shared face


def test_the_pack_lists_it_in_its_own_section(tmp_path: Path, step_files) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "pack"
    res = CliRunner().invoke(
        app,
        [
            "pack",
            str(step_files["bore_pair_assembly"]),
            "--out",
            str(out),
            "--no-images",
            "--no-timestamp",
        ],
    )
    assert res.exit_code == 0, res.output
    (assembly,) = list(out.rglob("02_assembly.md"))
    text = assembly.read_text(encoding="utf-8")
    fasteners = text.split("## Fastener joints", 1)[1].split("##", 1)[0]
    assert "J001" not in fasteners and "none found" in fasteners
    assert "## Pivot candidates" not in text
    section = text.split("## Large coaxial bore pairs", 1)[1].split("##", 1)[0]
    assert "J001" in section and "locating feature or bearing seat" in section
    assert "not a fastener" in section
