"""The ray casts of hole detection can be spread over the pool without changing a single result.

Finding the concave faces of a big part costs one point-in-solid query per cylinder or cone face,
and those queries are independent. The pool used to run all of them inside the one worker that
analyses the part, which made that part the slowest thing in the run. These tests pin that the
queries split into chunks, run anywhere and put back in face order give exactly the bores and
warnings of the serial loop, and that a part analysed with its bores found beforehand is the same
Part as one analysed alone.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest
from build123d import Box, Cone, Cylinder, Location, Pos, Rot
from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape

from stepscribe import api
from stepscribe.analysis import AnalyzeOptions, analyze_brep_file, bore_chunk
from stepscribe.api import analyze_full
from stepscribe.features.holes import assemble_bores, find_bore_faces
from stepscribe.geometry.part_geom import PartGeom
from stepscribe.progress import Tracker


def _part_with_every_kind_of_bore() -> TopoDS_Shape:
    """Through holes, a counterbore, a blind hole, a countersink, a boss and a sliver, tilted."""
    p = Box(80, 60, 14)
    for x in (-30, -10, 10, 30):
        p -= Pos(x, 20, 0) * Cylinder(2.0 + 0.5 * (x > 0), 16)  # through holes, two sizes
    p -= Pos(-20, -15, 0) * Cylinder(3.0, 16)  # counterbore: a wide shallow bore over a narrow one
    p -= Pos(-20, -15, 4) * Cylinder(6.0, 6)
    p -= Pos(0, -15, -2) * Cylinder(2.5, 10)  # blind from the bottom
    p -= Pos(20, -15, 0) * Cylinder(1.5, 16)  # countersink: a cone on top of a bore
    p -= Pos(20, -15, 5) * Cone(1.5, 4.0, 4.0)
    p += Pos(0, 0, 9) * Cylinder(5.0, 6)  # a boss (a convex cylinder)
    p -= Pos(35, -20, 7) * Cylinder(
        0.03, 0.1
    )  # 0.05 mm deep: a cylinder face under the minimum size
    tilted = Location((12.0, -7.0, 31.0)) * Rot(X=33, Y=17, Z=71) * p
    return tilted.wrapped  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def brep(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("bore_chunks") / "part.brep"
    assert BRepTools.Write_s(_part_with_every_kind_of_bore(), str(path))
    return path


def _reload(path: Path) -> TopoDS_Shape:
    shape = TopoDS_Shape()
    assert BRepTools.Read_s(shape, str(path), BRep_Builder())
    return shape


def _same(a, b) -> None:  # type: ignore[no-untyped-def]
    assert len(a) == len(b)
    for x, y in zip(a, b, strict=True):
        assert (x.idx, x.kind) == (y.idx, y.kind)
        for name in ("origin", "direction"):
            assert np.array_equal(getattr(x, name), getattr(y, name)), name
        for name in ("span_deg", "v0", "v1", "radius_ref", "semi_angle"):
            assert getattr(x, name) == getattr(y, name), name


def test_chunks_in_any_order_give_the_serial_bores_and_warnings(brep: Path) -> None:
    serial = PartGeom("p", _reload(brep))
    want = find_bore_faces(serial)
    n = len(serial.table.faces)
    assert len(want) >= 8 and any(
        "smaller than" in w for w in serial.warnings
    )  # the part is rich enough
    results = []
    for lo in range(0, n, 7):
        results.extend(bore_chunk(str(brep), "p", lo, min(lo + 7, n)))
    random.Random(5).shuffle(results)  # chunks finish in any order
    bores, warnings = assemble_bores(results)
    _same(bores, want)
    assert warnings == serial.warnings


def test_a_part_analysed_with_its_bores_found_beforehand_is_the_same_part(brep: Path) -> None:
    opts = AnalyzeOptions()
    alone, _s, _b = analyze_brep_file(str(brep), "p", "p.step", opts, None)
    n = len(PartGeom("p", _reload(brep)).table.faces)
    results = [r for lo in range(0, n, 11) for r in bore_chunk(str(brep), "p", lo, min(lo + 11, n))]
    pre, _s2, _b2 = analyze_brep_file(
        str(brep), "p", "p.step", opts, None, bores=assemble_bores(results)
    )
    assert pre.model_dump() == alone.model_dump()  # holes, patterns, warnings, everything


def test_the_pool_with_split_hole_detection_gives_the_same_report(
    step_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    src = step_files["plates_with_clip_assembly"]

    def run(workers: str) -> tuple[dict, list[str]]:  # type: ignore[type-arg]
        monkeypatch.setenv("STEPSCRIBE_WORKERS", workers)
        messages: list[str] = []
        tracker = Tracker(lambda p: messages.append(p.message))
        report = analyze_full(src, AnalyzeOptions(no_timestamp=True), tracker).report
        return report.model_dump(), messages

    monkeypatch.setattr(api, "PARALLEL_MIN_PARTS", 1)
    monkeypatch.setattr(api, "PARALLEL_MIN_FACES", 1)
    monkeypatch.setattr(api, "HEAVY_BORE_FACES", 10**9)  # nothing is split
    plain, plain_msgs = run("2")
    assert not any("split" in m for m in plain_msgs)
    monkeypatch.setattr(api, "HEAVY_BORE_FACES", 1)  # every part is split
    split, split_msgs = run("2")
    assert any("split" in m for m in split_msgs), split_msgs
    assert split == plain
    one, _ = run("1")  # and a single process agrees with both
    assert one == plain
