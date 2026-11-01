"""A touch that is neither a face contact nor a fit is one kind, "edge_or_point".

Telling a line from a point took the number of closest-point solutions the solver returned, and
that number depends on the thread count, so the same file could be reported both ways. One kind is
the same every time. Pairs with a known contact: edge on edge, corner on corner, a cylinder on a
plane, a sphere on a plane, crossing rods; two boxes face to face stay a planar contact.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from contact_truth_fixtures import FIXTURES, write

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import Analysis, analyze_full

# the five shapes the determinism check names, plus two more known touches
FIVE = [
    "edge_edge_parallel",  # edge on edge (a line)
    "corner_corner",  # corner on corner (a point)
    "cylinder_on_plane",  # a line
    "sphere_on_plane",  # a point
    "cylinders_crossing",  # crossing rods (a point)
]
MORE = ["edge_edge_crossing", "cylinders_parallel"]
RUNS = 20
SENTENCE = re.compile(r"\S+ touches at an edge or point \S+\.")


def _analysis(tmp: Path, name: str) -> Analysis:
    return analyze_full(write(name, tmp), AnalyzeOptions(understanding=False))


@pytest.mark.parametrize("name", FIVE + MORE)
def test_every_touch_that_is_not_a_face_or_a_fit_is_one_kind(tmp_path: Path, name: str) -> None:
    asm = _analysis(tmp_path, name).report.assembly
    assert asm is not None
    assert [c.kind for c in asm.contacts] == ["edge_or_point"]
    sentences = [r.sentence for r in asm.relations if r.predicate == "adjacent_to"]
    assert len(sentences) == 1 and SENTENCE.fullmatch(sentences[0]), sentences


def test_two_boxes_face_to_face_stay_planar(tmp_path: Path) -> None:
    assert FIXTURES["face_to_face"][0] == "planar_face"
    asm = _analysis(tmp_path, "face_to_face").report.assembly
    assert asm is not None and [c.kind for c in asm.contacts] == ["planar_face"]


@pytest.mark.parametrize("name", FIVE)
def test_the_same_pair_analysed_twenty_times_is_byte_identical(tmp_path: Path, name: str) -> None:
    seen = set()
    for i in range(RUNS):
        asm = _analysis(tmp_path / str(i), name).report.assembly
        assert asm is not None
        seen.add(
            json.dumps(
                {
                    "contacts": [c.model_dump() for c in asm.contacts],
                    "relations": [r.sentence for r in asm.relations],
                },
                sort_keys=True,
            )
        )
    assert len(seen) == 1
    assert '"kind": "edge_or_point"' in next(iter(seen))


def test_the_kinematics_debug_reads_an_edge_or_point_contact() -> None:
    from stepscribe.understanding.kin_debug import _reason

    text = _reason(None, False, None, "edge_or_point", 0.0)  # type: ignore[arg-type]
    assert text.startswith("no connection classified for an edge or point contact")
    assert _reason(None, False, None, "planar_face", 0.0).startswith(  # type: ignore[arg-type]
        "no connection classified for a planar face contact"
    )
