"""Generated robot-arm assemblies with known kinematics (no vendor files)."""

from __future__ import annotations

from pathlib import Path

from assembly_fixtures import Node, write_assembly
from build123d import Axis, Box, Cylinder, Location, Pos, Shape
from generate_fixtures import FIXTURE_DIR

BORE_D = 30.0  # a pivot bore: no screw size matches this diameter, and it is over the 20 mm minimum


def _bore(shape: Shape, axis: str, at: tuple[float, float, float], length: float = 1000.0) -> Shape:
    """Cut a Ø30 bore along *axis* through the point *at*."""
    cyl = Cylinder(BORE_D / 2, length)
    if axis == "X":
        cyl = cyl.rotate(Axis.Y, 90)
    elif axis == "Y":
        cyl = cyl.rotate(Axis.X, 90)
    return shape - Pos(*at) * cyl


def _box(x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]) -> Shape:
    """A box spanning the given global ranges."""
    return Pos((x[0] + x[1]) / 2, (y[0] + y[1]) / 2, (z[0] + z[1]) / 2) * Box(
        x[1] - x[0], y[1] - y[0], z[1] - z[0]
    )


def arm_6_axis(
    out: Path = FIXTURE_DIR, prefix: str = "ARM_rev0_", occurrence: bool = False
) -> Path:
    """BASE + LINK1..LINK6 with planar flange interfaces and perpendicular pivot bores.

    Ground truth: axes Z, Y, Y, X, Y, X.  Every interface is a large planar contact whose normal
    equals the pivot axis, and each pivot is a Ø30 bore pair (no screw size) on its own line.
    With *occurrence* the odd instances carry assembly-tree labels NAUO<n>, as vendor files do.
    The geometry is placed in global coordinates, so every instance sits at the identity.
    """
    base = _box((-70, 70), (-40, 40), (-20, 0))
    link1 = _box((-50, 50), (-40, 40), (0, 80))
    link2 = _box((-50, 50), (40, 120), (0, 80))
    link3 = _box((-50, 50), (120, 200), (0, 80))
    link4 = _box((50, 130), (120, 200), (0, 80))
    link5 = _box((50, 130), (200, 280), (0, 80))
    link6 = _box((130, 210), (200, 280), (0, 80))
    # joints 2 and 3 about Y: two separate bore lines through LINK2
    link1, link2 = _bore(link1, "Y", (-26, 0, 40)), _bore(link2, "Y", (-26, 0, 40))
    link2, link3 = _bore(link2, "Y", (26, 0, 40)), _bore(link3, "Y", (26, 0, 40))
    # joint 4 about X (LINK3 | LINK4); joint 5 about Y (LINK4 | LINK5) has only a short Ø30 recess in
    # each face (20 mm in all, shorter than its diameter), like the real ABB wrist; joint 6 about X
    link3, link4 = _bore(link3, "X", (0, 160, 60)), _bore(link4, "X", (0, 160, 60))
    link4, link5 = _bore(link4, "Y", (90, 195, 20), 10.0), _bore(link5, "Y", (90, 205, 20), 10.0)
    link5, link6 = _bore(link5, "X", (0, 240, 60)), _bore(link6, "X", (0, 240, 60))
    parts = {
        "BASE": base,
        "LINK1": link1,
        "LINK2": link2,
        "LINK3": link3,
        "LINK4": link4,
        "LINK5": link5,
        "LINK6": link6,
    }
    labels = {
        n: (f"NAUO{k}" if occurrence and k % 2 and k > 1 else f"{prefix}{n}")
        for k, n in enumerate(parts, 1)
    }
    root = Node("Arm", children=[Node(labels[n], f"{prefix}{n}", Location()) for n in parts])
    protos = {f"{prefix}{n}": s for n, s in parts.items()}
    suffix = "_occurrence" if occurrence else ""
    return write_assembly(out / f"arm_6_axis{suffix}.step", protos, root)


def arm_axis_disagree(out: Path = FIXTURE_DIR) -> Path:
    """BASE, LINK1..LINK3 where LINK1/LINK2 meet on a Z-normal flange but pivot on an X bore (clevis).

    LINK2 sits on LINK1 (flange normal +Z, 6400 mm2).  LINK1 has an ear beside LINK2 (0.3 mm
    apart, so not a contact) and both are drilled along X: the pivot axis (X) is perpendicular to
    the flange normal (Z).
    """
    base = _box((-60, 60), (-40, 40), (-20, 0))
    link1 = _box((-40, 40), (-40, 40), (0, 80)) + _box((40.3, 60), (-40, 40), (0, 140))
    link2 = _box((-40, 40), (-40, 40), (80, 160))
    link1 = _bore(link1, "X", (0, 0, 110), 200.0)
    link2 = _bore(link2, "X", (0, 0, 110), 200.0)
    link3 = _box((-40, 40), (-40, 40), (160, 240))
    parts = {"BASE": base, "LINK1": link1, "LINK2": link2, "LINK3": link3}
    root = Node("Arm", children=[Node(n, n, Location()) for n in parts])
    return write_assembly(out / "arm_axis_disagree.step", parts, root)


def named_links_resting(out: Path = FIXTURE_DIR) -> Path:
    """BASE and LINK1..LINK3 bars stacked on each other with no pivot, fastener or bore."""
    parts = {"BASE": _box((-60, 60), (-60, 60), (-20, 0))}
    for k in (1, 2, 3):
        parts[f"LINK{k}"] = _box((-10, 10), (-10, 10), (40 * (k - 1), 40 * k))
    root = Node("Stack", children=[Node(n, n, Location()) for n in parts])
    return write_assembly(out / "named_links_resting.step", parts, root)


def named_two_links(out: Path = FIXTURE_DIR) -> Path:
    """Two bars named LINK1 and LINK2 side by side, nothing joining them."""
    parts = {
        "LINK1": _box((-10, 10), (-10, 10), (0, 40)),
        "LINK2": _box((30, 50), (-10, 10), (0, 40)),
    }
    root = Node("Pair", children=[Node(n, n, Location()) for n in parts])
    return write_assembly(out / "named_two_links.step", parts, root)
