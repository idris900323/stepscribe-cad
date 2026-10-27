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


def test_the_split_follows_the_memory_rule_of_the_worker_cap() -> None:
    from stepscribe import analysis as A

    gb = 1024**3
    need = A.estimate_worker_mb(2000) * 1024**2  # one worker holding the largest part
    ok = A.may_split_bores
    assert ok(4, 2000, available_bytes=8 * gb, jobs=1)  # plenty of memory
    assert not ok(
        1, 2000, available_bytes=8 * gb, jobs=1
    )  # a single process has nobody to share with
    assert not ok(4, 2000, available_bytes=1, jobs=1)  # low memory: serial
    just = int(4 * need / A.RAM_SHARE)
    assert ok(4, 2000, available_bytes=just + 1, jobs=1)  # exactly what worker_count allows
    assert not ok(4, 2000, available_bytes=just - 1024, jobs=1)
    assert not ok(4, 2000, available_bytes=just + 1, jobs=2)  # the memory is shared between jobs
    # it never splits where worker_count would not have started that many workers
    for free in (gb, 2 * gb, 4 * gb, 16 * gb):
        n = A.worker_count(40, max_faces=2000, available_bytes=free, cpus=16, jobs=1)
        assert n == 1 or ok(n, 2000, available_bytes=free, jobs=1)


def test_unknown_free_memory_uses_a_conservative_default() -> None:
    from stepscribe import analysis as A

    limit = A.UNKNOWN_RAM_SPLIT_WORKERS
    assert limit == 4
    assert A.may_split_bores(limit, 2000, available_bytes=None, jobs=1)
    assert not A.may_split_bores(limit + 1, 2000, available_bytes=None, jobs=1)


def test_macos_style_missing_ram_query_is_the_unknown_case(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import sys

    from stepscribe import analysis as A

    def no_such_name(_name: str) -> int:
        raise ValueError("unrecognized configuration name")

    monkeypatch.setattr(os, "sysconf", no_such_name, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")  # the query inside may_split_bores too
    assert A.available_ram_bytes() is None
    assert A.may_split_bores(2, 2000, jobs=1)
    assert not A.may_split_bores(8, 2000, jobs=1)


def test_low_free_memory_runs_serial_and_gives_the_same_report(
    step_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from stepscribe import analysis as A

    src = step_files["plates_with_clip_assembly"]

    def run() -> tuple[dict, list[str]]:  # type: ignore[type-arg]
        messages: list[str] = []
        tracker = Tracker(lambda p: messages.append(p.message))
        report = analyze_full(src, AnalyzeOptions(no_timestamp=True), tracker).report
        return report.model_dump(), messages

    monkeypatch.setenv("STEPSCRIBE_WORKERS", "2")
    monkeypatch.setattr(api, "PARALLEL_MIN_PARTS", 1)
    monkeypatch.setattr(api, "PARALLEL_MIN_FACES", 1)
    monkeypatch.setattr(api, "HEAVY_BORE_FACES", 1)  # every part would be split
    monkeypatch.setattr(A, "available_ram_bytes", lambda platform=None: 64 * 1024**3)
    split, split_msgs = run()
    assert any("split" in m for m in split_msgs), split_msgs
    monkeypatch.setattr(A, "available_ram_bytes", lambda platform=None: 1024**2)  # 1 MB free
    serial, serial_msgs = run()
    assert not any("split" in m for m in serial_msgs), serial_msgs
    assert serial == split


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

    from stepscribe import analysis as A

    # the split follows the memory rule: pin the free memory so the test does not depend on the machine
    monkeypatch.setattr(A, "available_ram_bytes", lambda platform=None: 64 * 1024**3)
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
