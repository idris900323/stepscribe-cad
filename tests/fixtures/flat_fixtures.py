"""A shaft end with a flatted (D-shaped) counterbore, and the same shaft with a plain round one.

Ø8 x 24 shaft along Z, top at z = +12. A Ø4.2 counterbore 8.6 deep is cut from the top, with a Ø1.3
through hole on the axis in its floor. In the flat variants a flat 1.5 mm from the axis truncates the
counterbore, so the numbers worked out by hand are

* across flats           1.5 + 2.1 = 3.6
* chord of the flat      2 x sqrt(2.1^2 - 1.5^2) = 2.94
* flat depth             8.6
* hole wall to the flat  1.5 - 0.65 = 0.85
* hole wall to the round counterbore wall opposite  2.1 - 0.65 = 1.45

``d_bore_flat_rounded`` has a 0.4 mm fillet round the mouth of the bore, as a real part often does.
``d_bore_flat_corners`` has the flat's two corners rounded (R0.3).
``d_bore_flat_short`` has the flat over the top 3 mm only: not a flat along the bore, so it is not described.
"""

from __future__ import annotations

from pathlib import Path

from build123d import Box, Cylinder, Pos, Shape, export_step, fillet
from generate_fixtures import FIXTURE_DIR

TOP = 12.0
DEPTH = 8.6
BORE_R = 2.1
HOLE_R = 0.65
FLAT = 1.5


def _shaft(flat: bool) -> Shape:
    cutter = Pos(0, 0, TOP - DEPTH / 2) * Cylinder(BORE_R, DEPTH)
    if flat:
        cutter = cutter & (Pos(FLAT - 5, 0, TOP - DEPTH / 2) * Box(10, 10, DEPTH))  # x <= FLAT
    return Cylinder(4.0, 24) - cutter - Cylinder(HOLE_R, 30)


def d_bore_flat() -> Shape:
    return _shaft(True)


def d_bore_round() -> Shape:
    return _shaft(False)


def d_bore_flat_rounded() -> Shape:
    shaft = _shaft(True)
    mouth = [
        e
        for e in shaft.edges()
        if abs(e.center().Z - TOP) < 1e-6 and e.bounding_box().max.X < 3.0  # not the Ø8 rim
    ]
    return fillet(mouth, 0.4)


def d_bore_flat_corners() -> Shape:
    """The flat's two corners with the round wall are rounded (R0.3), which shortens the flat's face."""
    shaft = _shaft(True)
    corners = [
        e
        for e in shaft.edges()
        if abs(e.length - DEPTH) < 1e-6
        and abs(e.center().X - FLAT) < 0.5
        and abs(e.center().Y) > 1.0
    ]
    return fillet(corners, 0.3)


def d_bore_flat_short() -> Shape:
    """The flat covers only the top 3 mm of the 8.6 mm counterbore, a ledge and not a flat along the bore."""
    cutter = Pos(0, 0, TOP - DEPTH / 2) * Cylinder(BORE_R, DEPTH)
    ledge = Pos(FLAT + 2.5, 0, TOP - 1.5) * Box(5, 10, 3)  # x >= FLAT, the top 3 mm
    return Cylinder(4.0, 24) - (cutter - ledge) - Cylinder(HOLE_R, 30)


FLAT_FIXTURES = {
    "d_bore_flat": d_bore_flat,
    "d_bore_round": d_bore_round,
    "d_bore_flat_rounded": d_bore_flat_rounded,
    "d_bore_flat_corners": d_bore_flat_corners,
    "d_bore_flat_short": d_bore_flat_short,
}


def generate_flat(out: Path = FIXTURE_DIR) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, fn in FLAT_FIXTURES.items():
        p = out / f"{name}.step"
        export_step(fn(), str(p))
        paths[name] = p
    return paths
