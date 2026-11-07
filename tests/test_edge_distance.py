"""A hole's edge distance is the wall left around its sides, not the gap below a drill-point tip."""

from __future__ import annotations

import pytest


def holes(analyses):  # type: ignore[no-untyped-def]
    part = analyses("tip_over_cavity").report.parts[0]
    flat = next(h for h in part.holes if h.axis.origin.x < 0)
    drilled = next(h for h in part.holes if h.axis.origin.x > 0)
    return flat, drilled


def test_the_fixture_has_the_two_hole_kinds(analyses) -> None:  # type: ignore[no-untyped-def]
    flat, drilled = holes(analyses)
    assert flat.bottom_type == "flat" and drilled.bottom_type == "drill_point"
    assert flat.diameter_mm == pytest.approx(6.0) and drilled.diameter_mm == pytest.approx(6.0)
    assert not flat.is_through and not drilled.is_through


def test_a_drill_point_tip_is_not_counted_as_the_edge(analyses) -> None:  # type: ignore[no-untyped-def]
    """The tip is 1.0 mm above the cavity ceiling, the shoulder rim 2.8 mm: the wall is 2.8 mm."""
    _flat, drilled = holes(analyses)
    assert drilled.edge_distance_mm == pytest.approx(2.8, abs=0.05)


def test_a_flat_bottom_is_still_measured_as_before(analyses) -> None:  # type: ignore[no-untyped-def]
    """A flat bottom's rim sits at the floor level, so the 0.8 mm of material under it is the answer."""
    flat, _drilled = holes(analyses)
    assert flat.edge_distance_mm == pytest.approx(0.8, abs=0.05)


def test_the_weak_spot_for_the_flat_hole_remains_and_names_the_measured_distance(analyses) -> None:  # type: ignore[no-untyped-def]
    u = analyses("tip_over_cavity").report.understanding
    assert u is not None
    spots = [w for w in u.weak_spots if w.category == "edge_distance"]
    assert spots and all(w.value is not None for w in spots)
    assert min(w.value for w in spots if w.value is not None) == pytest.approx(0.8, abs=0.05)
