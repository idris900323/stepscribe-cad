"""Complex parts for the process-guess rule: sculpted, merely complex, and thin-walled and ribbed."""

from __future__ import annotations

from pathlib import Path

from build123d import Box, Circle, Cylinder, Plane, Pos, export_step, loft
from generate_fixtures import FIXTURE_DIR

# a Ø3 hole whose edge is 1.0 mm from the plate edge (guideline 1.5 x 3 = 4.5 mm)
EDGE_HOLE = (-47.5, 0.0)


def _drilled(body):  # type: ignore[no-untyped-def]
    return body - Pos(EDGE_HOLE[0], EDGE_HOLE[1], 0) * Cylinder(1.5, 30)


def freeform_housing(out: Path = FIXTURE_DIR) -> Path:
    """A plate with 64 sculpted bumps: 130+ faces, about half of them B-spline, and one hole near the edge."""
    body = Box(100, 100, 10)
    for i in range(8):
        for j in range(8):
            x, y = -42 + i * 12, -42 + j * 12
            sections = [
                Plane.XY.offset(5) * Pos(x, y, 0) * Circle(3.0),
                Plane.XY.offset(8) * Pos(x, y, 0) * Circle(4.5),
                Plane.XY.offset(11) * Pos(x, y, 0) * Circle(2.0),
            ]
            body = body + loft(sections)
    p = out / "freeform_housing.step"
    p.parent.mkdir(parents=True, exist_ok=True)
    export_step(_drilled(body), str(p))
    return p


def bossed_plate(out: Path = FIXTURE_DIR) -> Path:
    """As complex as the housing (130+ faces) but every face is a plane or a cylinder; same edge hole."""
    body = Box(100, 100, 10)
    for i in range(8):
        for j in range(8):
            body = body + Pos(-42 + i * 12, -42 + j * 12, 7.5) * Cylinder(3.0, 5)
    p = out / "bossed_plate.step"
    p.parent.mkdir(parents=True, exist_ok=True)
    export_step(_drilled(body), str(p))
    return p


def ribbed_housing(out: Path = FIXTURE_DIR) -> Path:
    """An open box with 1 mm walls and a grid of 1 mm ribs: 100+ planar faces, a valid solid, and a
    volume under 10 % of its bounding box. Thin and complex, but ordinary geometry."""
    outer = Box(120, 120, 40)
    body = outer - Pos(0, 0, 0.5) * Box(118, 118, 39)  # 1 mm walls and floor, open at the top
    for k in range(5):  # ribs 12 mm high standing on the floor (its top face is at z = -19)
        pos = -40 + k * 20
        body = body + Pos(pos, 0, -13) * Box(1, 118, 12) + Pos(0, pos, -13) * Box(118, 1, 12)
    p = out / "ribbed_housing.step"
    p.parent.mkdir(parents=True, exist_ok=True)
    export_step(body, str(p))
    return p
