"""Fixtures for problems found in a real design (a large thin front plate, rotated parts)."""

from __future__ import annotations

import math
from pathlib import Path

from assembly_fixtures import Node, write_assembly
from build123d import Box, Cylinder, Location, Pos
from build123d import export_step as _export
from generate_fixtures import FIXTURE_DIR
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf


def large_thin_plate(out: Path = FIXTURE_DIR) -> Path:
    """183 x 135 x 6 plate with ten Ø2.6 holes through its thickness (like a front panel)."""
    plate = Box(183, 135, 6)
    for x in (-80, -40, 0, 40, 80):
        for y in (-55, 55):
            plate = plate - Pos(x, y, 0) * Cylinder(1.3, 8)
    p = out / "large_thin_plate.step"
    p.parent.mkdir(parents=True, exist_ok=True)
    _export(plate, str(p))
    return p


def plain_shaft(out: Path = FIXTURE_DIR) -> Path:
    """Stepped shaft: Ø8 x 60 with a Ø12 x 10 collar."""
    shaft = Cylinder(4, 60) + Pos(0, 0, -25) * Cylinder(6, 10)
    p = out / "plain_shaft.step"
    _export(shaft, str(p))
    return p


def round_disc(out: Path = FIXTURE_DIR) -> Path:
    """Ø60 x 6 disc with four Ø3 holes parallel to its axis."""
    disc = Cylinder(30, 6)
    for x, y in ((15, 15), (-15, 15), (15, -15), (-15, -15)):
        disc = disc - Pos(x, y, 0) * Cylinder(1.5, 8)
    p = out / "round_disc.step"
    _export(disc, str(p))
    return p


def _about(
    axis: tuple[float, float, float], degrees: float, at: tuple[float, float, float]
) -> Location:
    trsf = gp_Trsf()
    trsf.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*axis)), math.radians(degrees))
    moved = gp_Trsf()
    moved.SetTranslation(gp_Pnt(0, 0, 0), gp_Pnt(*at))
    return Location(moved.Multiplied(trsf))


def rotated_assembly(out: Path = FIXTURE_DIR) -> Path:
    """Three bars: one upright, one turned 90 deg about X, one turned 120 deg about (1,1,1)."""
    bar = Box(40, 10, 6)
    root = Node(
        "Rotated",
        children=[
            Node("Upright", "Bar", Location()),
            Node("QuarterTurn", "Bar", _about((1, 0, 0), 90, (0, 60, 0))),
            Node("ThirdTurn", "Bar", _about((1, 1, 1), 120, (0, 0, 60))),
        ],
    )
    return write_assembly(out / "rotated_assembly.step", {"Bar": bar}, root)


def generate_pack_issue_fixtures(out: Path = FIXTURE_DIR) -> dict[str, Path]:
    return {
        fn.__name__: fn(out) for fn in (large_thin_plate, plain_shaft, round_disc, rotated_assembly)
    }
