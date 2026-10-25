"""The pair distance is computed once and equals the old constructor-plus-Perform result.

OCCT's BRepExtrema_DistShapeShape(shape1, shape2) already runs the (single-threaded) computation, so
the extra SetMultiThread/Perform that followed it repeated all the work. These tests pin that the
single computation gives the same distance, solution count and closest points, and that contacts
at the tolerance boundaries are classified as before.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from assembly_fixtures import Node, write_assembly
from build123d import Box, Location
from OCP.BRepExtrema import BRepExtrema_DistShapeShape

from stepscribe import config
from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.assembly.contacts import _distance

TOL = config.CONTACT_TOL
GAPS = [0.0, TOL * 0.98, TOL, TOL * 1.02, 0.5, config.NEAR_MISS_MAX * 1.2]


def _pair(tmp: Path, gap: float) -> Path:
    plate = Box(20, 20, 5)
    root = Node(
        "Pair",
        children=[
            Node("Lower", "plate", Location()),
            Node("Upper", "plate", Location((0, 0, 5 + gap))),
        ],
    )
    return write_assembly(tmp / f"gap_{gap:.5f}.step", {"plate": plate}, root)


def _old_way(a, b):  # type: ignore[no-untyped-def]
    dss = BRepExtrema_DistShapeShape(a, b)
    dss.SetMultiThread(True)
    dss.Perform()
    return dss


def _points(dss) -> list[tuple[float, ...]]:  # type: ignore[no-untyped-def]
    out = []
    for i in range(1, dss.NbSolution() + 1):
        p, q = dss.PointOnShape1(i), dss.PointOnShape2(i)
        out.append(tuple(np.round([p.X(), p.Y(), p.Z(), q.X(), q.Y(), q.Z()], 9)))
    return out


@pytest.mark.parametrize("gap", GAPS)
def test_single_computation_equals_the_old_two_step_result(tmp_path: Path, gap: float) -> None:
    analysis = analyze_full(_pair(tmp_path, gap), AnalyzeOptions(understanding=False))
    from stepscribe.assembly import build_instances

    a, b = build_instances(analysis)[:2]
    old, new = _old_way(a.shape, b.shape), _distance(a.shape, b.shape)
    assert new.IsDone() and old.IsDone()
    assert new.Value() == old.Value()
    assert new.NbSolution() == old.NbSolution()
    assert _points(new) == _points(old)


@pytest.mark.parametrize("gap", GAPS)
def test_contact_kind_at_the_tolerance_boundaries(tmp_path: Path, gap: float) -> None:
    analysis = analyze_full(_pair(tmp_path, gap), AnalyzeOptions(understanding=False))
    from stepscribe.assembly import build_instances

    a, b = build_instances(analysis)[:2]
    old_distance = float(_old_way(a.shape, b.shape).Value())
    contacts = analysis.report.assembly.contacts  # type: ignore[union-attr]
    if old_distance >= config.NEAR_MISS_MAX:
        assert contacts == []
        return
    assert len(contacts) == 1
    touching = old_distance < TOL
    assert (contacts[0].kind != "near_miss") == touching
    assert contacts[0].min_distance_mm == pytest.approx(old_distance, abs=0)
