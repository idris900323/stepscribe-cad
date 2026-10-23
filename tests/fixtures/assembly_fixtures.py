"""Assembly fixtures written with XCAF so that prototypes are genuinely shared (ground truth known)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from build123d import Axis, Box, Cylinder, Location, Pos, Rot, Shape
from generate_fixtures import FIXTURE_DIR
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool


@dataclass
class Node:
    """An instance in the assembly tree: a prototype part, or a subassembly with children."""

    name: str
    proto: str | None = None
    loc: Location = field(default_factory=Location)
    children: list[Node] = field(default_factory=list)


def _set_name(label: TDF_Label, name: str) -> None:
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))


def write_assembly(path: Path, protos: dict[str, Shape], root: Node) -> Path:
    """Write a STEP assembly: *protos* are shared prototypes, *root* the instance tree."""
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-CAF"))
    app.InitDocument(doc)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    proto_labels: dict[str, TDF_Label] = {}
    for name, shape in protos.items():
        label = tool.AddShape(shape.wrapped, False)
        _set_name(label, name)
        proto_labels[name] = label

    def build(node: Node) -> TDF_Label:
        asm = tool.NewShape()
        _set_name(asm, node.name)
        for child in node.children:
            target = proto_labels[child.proto] if child.proto else build(child)
            comp = tool.AddComponent(asm, target, child.loc.wrapped)
            _set_name(comp, child.name)
        return asm

    build(root)
    tool.UpdateAssemblies()
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    writer.Transfer(doc, STEPControl_AsIs)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer.Write(str(path))
    return path


def _plate(with_holes: bool = True) -> Shape:
    p = Box(60, 60, 5)
    if with_holes:
        for x in (-20, 20):
            for y in (-20, 20):
                p = p - Pos(x, y, 0) * Cylinder(1.7, 6)
    return p


def two_plates_assembly(out: Path = FIXTURE_DIR) -> Path:
    """One 'Plate' prototype used twice: BasePlate, and TopPlate resting on it (grip 10, 4 joints)."""
    root = Node(
        "TwoPlates",
        children=[
            Node("BasePlate", "Plate", Location()),
            Node("TopPlate", "Plate", Location((0, 0, 5))),
        ],
    )
    return write_assembly(out / "two_plates_assembly.step", {"Plate": _plate()}, root)


def tapped_assembly(out: Path = FIXTURE_DIR) -> Path:
    """Clearance plate (Ø3.4 x4, 5 thick) on a block with four blind Ø2.5 x 8 tapped holes."""
    block = Box(60, 60, 12)
    for x in (-20, 20):
        for y in (-20, 20):
            block = block - Pos(x, y, 6 - 4) * Cylinder(1.25, 8)
    root = Node(
        "Tapped",
        children=[
            Node("Block", "Block", Pos(0, 0, -6)),
            Node("Cover", "Plate", Pos(0, 0, 2.5)),
        ],
    )
    return write_assembly(out / "tapped_assembly.step", {"Block": block, "Plate": _plate()}, root)


def blind_clearance_assembly(out: Path = FIXTURE_DIR) -> Path:
    """Cover plate (6 thick, Ø2.6 through x4) on a block with four 7 deep flat-bottomed Ø2.6 holes.

    The blind hole is the end of the stack: a nut cannot reach it, so the screw can be at most 13 long.
    """
    block = Box(60, 60, 12)
    for x in (-20, 20):
        for y in (-20, 20):
            block = block - Pos(x, y, 6 - 3.5) * Cylinder(1.3, 7)
    cover = Box(60, 60, 6)
    for x in (-20, 20):
        for y in (-20, 20):
            cover = cover - Pos(x, y, 0) * Cylinder(1.3, 8)
    root = Node(
        "BlindClearance",
        children=[
            Node("Block", "Block", Pos(0, 0, -6)),
            Node("Cover", "Cover", Pos(0, 0, 3)),
        ],
    )
    return write_assembly(
        out / "blind_clearance_assembly.step", {"Block": block, "Cover": cover}, root
    )


def blind_thin_stack_assembly(out: Path = FIXTURE_DIR) -> Path:
    """3 mm cover over a block with four 3 mm deep blind Ø1.6 holes: a 6 mm stack like an LED mount."""
    block = Box(40, 40, 10)
    for x in (-12, 12):
        for y in (-12, 12):
            block = block - Pos(x, y, 5 - 1.5) * Cylinder(0.8, 3)
    cover = Box(40, 40, 3)
    for x in (-12, 12):
        for y in (-12, 12):
            cover = cover - Pos(x, y, 0) * Cylinder(0.8, 5)
    root = Node(
        "BlindThin",
        children=[Node("Block", "Block", Pos(0, 0, -5)), Node("Cover", "Cover", Pos(0, 0, 1.5))],
    )
    return write_assembly(
        out / "blind_thin_stack_assembly.step", {"Block": block, "Cover": cover}, root
    )


def pilot_over_blind_assembly(out: Path = FIXTURE_DIR) -> Path:
    """6 mm plate with Ø3.2 through holes over a block with 7 deep blind Ø2.6 pilot holes (M3 x 12)."""
    block = Box(60, 60, 12)
    for x in (-20, 20):
        for y in (-20, 20):
            block = block - Pos(x, y, 6 - 3.5) * Cylinder(1.3, 7)
    cover = Box(60, 60, 6)
    for x in (-20, 20):
        for y in (-20, 20):
            cover = cover - Pos(x, y, 0) * Cylinder(1.6, 8)
    root = Node(
        "PilotOverBlind",
        children=[
            Node("Block", "Block", Pos(0, 0, -6)),
            Node("Cover", "Cover", Pos(0, 0, 3)),
        ],
    )
    return write_assembly(
        out / "pilot_over_blind_assembly.step", {"Block": block, "Cover": cover}, root
    )


def pilot_thin_assembly(out: Path = FIXTURE_DIR) -> Path:
    """3 mm cover with Ø2.3 through holes over a block with 3 deep blind Ø1.6 holes (M2 x 5)."""
    block = Box(40, 40, 10)
    for x in (-12, 12):
        for y in (-12, 12):
            block = block - Pos(x, y, 5 - 1.5) * Cylinder(0.8, 3)
    cover = Box(40, 40, 3)
    for x in (-12, 12):
        for y in (-12, 12):
            cover = cover - Pos(x, y, 0) * Cylinder(1.15, 5)
    root = Node(
        "PilotThin",
        children=[Node("Block", "Block", Pos(0, 0, -5)), Node("Cover", "Cover", Pos(0, 0, 1.5))],
    )
    return write_assembly(out / "pilot_thin_assembly.step", {"Block": block, "Cover": cover}, root)


def occurrence_label_assembly(out: Path = FIXTURE_DIR) -> Path:
    """Three bars; two instances carry assembly-tree occurrence labels (NAUO4, NAUO7) like vendor files."""
    root = Node(
        "Arm",
        children=[
            Node("NAUO4", "LINK3", Pos(0, 0, 0)),
            Node("Holder", "LINK2", Pos(0, 0, 10)),
            Node("NAUO7", "LINK6", Pos(0, 0, 20)),
        ],
    )
    return write_assembly(
        out / "occurrence_label_assembly.step",
        {"LINK3": Box(20, 20, 10), "LINK2": Box(20, 20, 10), "LINK6": Box(20, 20, 10)},
        root,
    )


def pivot_pair_assembly(out: Path = FIXTURE_DIR) -> Path:
    """Two blocks side by side on the X axis, each with a coaxial Ø50 bore (a pivot, no screw size)."""
    a = Box(40, 80, 80) - Cylinder(25, 50).rotate(Axis.Y, 90)
    b = Box(20, 80, 80) - Cylinder(25, 30).rotate(Axis.Y, 90)
    root = Node(
        "Pivot",
        children=[Node("LINK1", "A", Pos(0, 0, 0)), Node("LINK2", "B", Pos(30, 0, 0))],
    )
    return write_assembly(out / "pivot_pair_assembly.step", {"A": a, "B": b}, root)


def shaft_in_bearing_assembly(out: Path = FIXTURE_DIR) -> Path:
    """Ø8 shaft in a Ø8.06 bore (diametral clearance 0.06)."""
    block = Box(30, 30, 20) - Cylinder(4.03, 22)
    shaft = Cylinder(4.0, 40)
    root = Node(
        "ShaftAssy",
        children=[Node("Housing", "Housing", Location()), Node("Shaft", "Shaft", Location())],
    )
    return write_assembly(
        out / "shaft_in_bearing_assembly.step", {"Housing": block, "Shaft": shaft}, root
    )


def nested_assembly(out: Path = FIXTURE_DIR) -> Path:
    """Robot > Arm > Gripper > Finger x2, with translated and rotated levels."""
    finger = Box(10, 4, 20)
    base = Box(40, 40, 10)
    inner = Node(
        "Gripper",
        loc=Pos(0, 0, 30),
        children=[
            Node("FingerL", "Finger", Pos(-8, 0, 0)),
            Node("FingerR", "Finger", Pos(8, 0, 0)),
        ],
    )
    arm = Node("Arm", loc=Pos(100, 0, 0) * Rot(0, 0, 90), children=[inner])
    root = Node("Robot", children=[Node("Base", "Base", Location()), arm])
    return write_assembly(out / "nested_assembly.step", {"Finger": finger, "Base": base}, root)


def generate_assemblies(out: Path = FIXTURE_DIR) -> dict[str, Path]:
    """Write all assembly fixtures; returns name -> path."""
    builders = (
        two_plates_assembly,
        tapped_assembly,
        blind_clearance_assembly,
        blind_thin_stack_assembly,
        occurrence_label_assembly,
        pivot_pair_assembly,
        pilot_over_blind_assembly,
        pilot_thin_assembly,
        shaft_in_bearing_assembly,
        nested_assembly,
    )
    from robot_fixtures import arm_6_axis, arm_axis_disagree, named_links_resting

    out_map = {fn.__name__: fn(out) for fn in builders}
    out_map["arm_6_axis"] = arm_6_axis(out)
    out_map["arm_6_axis_occurrence"] = arm_6_axis(out, occurrence=True)
    out_map["arm_axis_disagree"] = arm_axis_disagree(out)
    out_map["named_links_resting"] = named_links_resting(out)
    return out_map


if __name__ == "__main__":
    for n, p in generate_assemblies().items():
        print(n, p)
