"""Ground-truth contact fixtures: two shapes at identity, touching in a known way (lengths in mm).

``FIXTURES`` maps a name to (what the contact really is, builder).
"""

from __future__ import annotations

import math
from pathlib import Path

from assembly_fixtures import Node, write_assembly
from build123d import Box, Cylinder, Location, Pos, Rot, Sphere

S2 = math.sqrt(2)


def _lowest_vertex(shape):
    v = sorted(shape.vertices(), key=lambda v: (v.Z, v.X, v.Y))[0]
    return v.X, v.Y, v.Z


def edge_edge_parallel():
    a = Box(20, 20, 20)
    b = Pos(0, 10, 10 + 10 * S2) * Rot(X=45) * Box(20, 20, 20)
    return a, b


def edge_edge_crossing():
    """A's ridge (top edge, along X) under B's lowest edge (along Y): one crossing point."""
    a = Rot(X=45) * Box(20, 20, 20)
    b = Pos(0, 0, 20 * S2) * Rot(Y=45) * Box(20, 20, 20)
    return a, b


def corner_corner():
    a = Box(20, 20, 20)
    b = (
        Rot(Y=math.degrees(math.atan(1 / S2))) * Rot(X=45) * Box(20, 20, 20)
    )  # body diagonal now vertical
    x, y, z = _lowest_vertex(b)
    return a, Pos(10 - x, 10 - y, 10 - z) * b


def cylinder_on_plane():
    return Box(60, 60, 5), Pos(0, 0, 2.5 + 8) * Rot(Y=90) * Cylinder(8, 30)


def sphere_on_plane():
    return Box(60, 60, 5), Pos(0, 0, 2.5 + 8) * Sphere(8)


def face_to_face():
    return Box(20, 20, 10), Pos(0, 0, 10) * Box(20, 20, 10)


def cylinders_crossing():
    return Rot(Y=90) * Cylinder(5, 30), Pos(0, 0, 10) * Rot(X=90) * Cylinder(5, 30)


def cylinders_parallel():
    return Rot(Y=90) * Cylinder(5, 30), Pos(0, 10, 0) * Rot(Y=90) * Cylinder(5, 30)


FIXTURES = {
    "edge_edge_parallel": ("line", edge_edge_parallel),
    "edge_edge_crossing": ("point", edge_edge_crossing),
    "corner_corner": ("point", corner_corner),
    "cylinder_on_plane": ("line", cylinder_on_plane),
    "sphere_on_plane": ("point", sphere_on_plane),
    "face_to_face": ("planar_face", face_to_face),
    "cylinders_crossing": ("point", cylinders_crossing),
    "cylinders_parallel": ("line", cylinders_parallel),
}


def write(name, out: Path, builder=None) -> Path:
    a, b = (builder or FIXTURES[name][1])()
    root = Node(name, children=[Node("A", "a", Location()), Node("B", "b", Location())])
    return write_assembly(out / f"{name}.step", {"a": a, "b": b}, root)
