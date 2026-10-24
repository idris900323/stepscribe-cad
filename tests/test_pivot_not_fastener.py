"""A pivot candidate (a wide, long bore with no screw size) is not a fastener anywhere."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stepscribe.cli import app
from stepscribe.understanding.questions import generate_questions

WORDS = re.compile(r"bolt|fasten|screw|\bnut\b", re.I)


def pair(analyses):  # type: ignore[no-untyped-def]
    report = analyses("pivot_pair_assembly").report
    assert report.assembly is not None and report.understanding is not None
    return report, report.assembly


def test_the_stack_is_a_pivot_candidate_and_not_in_the_fastener_list(analyses) -> None:  # type: ignore[no-untyped-def]
    _r, asm = pair(analyses)
    (j,) = asm.fastener_joints
    assert j.pivot_candidate and j.common_diameter_mm == pytest.approx(50.0)
    assert j.stack_thickness_mm >= 50
    assert asm.fasteners == [] and asm.pivots == [j]


def test_no_relation_calls_it_bolted_or_fastened(analyses) -> None:  # type: ignore[no-untyped-def]
    _r, asm = pair(analyses)
    for rel in asm.relations:
        assert rel.predicate != "bolted_to" and not WORDS.search(rel.sentence), rel.sentence


def test_the_shopping_list_and_the_summary_have_no_fasteners(analyses) -> None:  # type: ignore[no-untyped-def]
    report, asm = pair(analyses)
    assert asm.fastener_shopping_list == []
    assert report.understanding is not None
    assert not WORDS.search(report.understanding.summary), report.understanding.summary


def test_load_paths_do_not_hang_the_parts_on_a_fastener(analyses) -> None:  # type: ignore[no-untyped-def]
    report, _asm = pair(analyses)
    assert report.understanding is not None
    text = json.dumps([p.model_dump(mode="json") for p in report.understanding.load_paths])
    assert "fastened" not in text and not WORDS.search(text), text[:400]


def test_no_weak_spot_calls_it_a_fastener(analyses) -> None:  # type: ignore[no-untyped-def]
    report, _asm = pair(analyses)
    assert report.understanding is not None
    for w in report.understanding.weak_spots:
        assert w.category not in ("single_fastener", "cantilever", "short_screw"), w
        assert not WORDS.search(w.message), w.message


def test_the_interview_does_not_ask_whether_fasteners_are_missing(analyses) -> None:  # type: ignore[no-untyped-def]
    report, _asm = pair(analyses)
    for q in generate_questions(report, limit=None):
        assert q.kind != "connection_type" and not WORDS.search(q.text), q.text


def test_the_arm_fixtures_pivots_appear_in_no_relation(analyses) -> None:  # type: ignore[no-untyped-def]
    """Four pivots; the fifth stack is a 20 mm recess pair, too short for the pivot rule, so it stays
    an unmatched fastener record (confidence 0) and is not part of this check."""
    asm = analyses("arm_6_axis").report.assembly
    assert asm is not None and len(asm.pivots) == 4
    pivot_ids = {j.id for j in asm.pivots}
    for rel in asm.relations:
        assert not pivot_ids & set(rel.via), rel.sentence
        assert not (
            rel.predicate == "bolted_to"
            and WORDS.search(rel.sentence)
            and rel.via
            and set(rel.via) <= pivot_ids
        )
    assert {j.id for j in asm.fasteners}.isdisjoint(pivot_ids)


def test_a_real_bolted_pair_still_says_bolted(analyses) -> None:  # type: ignore[no-untyped-def]
    asm = analyses("two_plates_assembly").report.assembly
    assert asm is not None and len(asm.fasteners) == 4 and asm.pivots == []
    assert any(rel.predicate == "bolted_to" for rel in asm.relations)


def test_the_pack_lists_it_as_a_pivot_not_under_fastener_joints(tmp_path: Path, step_files) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "pack"
    res = CliRunner().invoke(
        app,
        [
            "pack",
            str(step_files["pivot_pair_assembly"]),
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
    pivots = text.split("## Pivot candidates", 1)[1].split("##", 1)[0]
    assert "J001" in pivots and "not a fastener" in pivots
