"""Complex parts for the process-guess rule: sculpted, merely complex, and thin-walled and ribbed."""

from __future__ import annotations

from pathlib import Path

from build123d import Box, Circle, Cone, Cylinder, Plane, Pos, export_step, loft
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


def ribbed_sculpted(out: Path = FIXTURE_DIR) -> Path:
    """The ribbed housing plus 49 sculpted bumps under its floor: planar ribs (sharp corners at their
    bases) and about 19 % free-form faces, so no process is guessed for it."""
    outer = Box(120, 120, 40)
    body = outer - Pos(0, 0, 0.5) * Box(118, 118, 39)
    for k in range(5):
        pos = -40 + k * 20
        body = body + Pos(pos, 0, -13) * Box(1, 118, 12) + Pos(0, pos, -13) * Box(118, 1, 12)
    for i in range(7):
        for j in range(7):
            x, y = -45 + i * 15, -45 + j * 15
            sections = [
                Plane.XY.offset(-20) * Pos(x, y, 0) * Circle(3.0),
                Plane.XY.offset(-23) * Pos(x, y, 0) * Circle(4.5),
                Plane.XY.offset(-26) * Pos(x, y, 0) * Circle(2.0),
            ]
            body = body + loft(sections)
    p = out / "ribbed_sculpted.step"
    p.parent.mkdir(parents=True, exist_ok=True)
    export_step(body, str(p))
    return p


def tip_over_cavity(out: Path = FIXTURE_DIR) -> Path:
    """A 30 mm block with a cavity under its middle (ceiling at z = 7.2) and two blind Ø6 holes from the top.

    Left (x = -12): flat bottom at z = 8.0, so 0.8 mm of material under it.
    Right (x = +12): drill point; the shoulder is at z = 10 (2.8 mm above the ceiling) and the tip
    at z = 8.2, 1.0 mm above the ceiling.
    """
    body = Box(60, 60, 30) - Pos(0, 0, 3.6) * Box(50, 50, 7.2)
    flat = Pos(-12, 0, 8.0 + 13.5) * Cylinder(3.0, 27)  # z 8.0 .. 35
    shaft = Pos(12, 0, 10.0 + 12.5) * Cylinder(3.0, 25)  # z 10 .. 35
    tip = Pos(12, 0, 9.1) * Cone(0.0, 3.0, 1.8)  # z 8.2 .. 10, point down
    p = out / "tip_over_cavity.step"
    p.parent.mkdir(parents=True, exist_ok=True)
    export_step(body - flat - shaft - tip, str(p))
    return p
