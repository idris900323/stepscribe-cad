"""STEP files written with the XCAF writer: colours, materials, layers, descriptions and dimensions.

Generated for the tests, never a vendor file. The product description is put into the file by editing
the PRODUCT line of the written text (the XCAF writer has no setter for it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.Interface import Interface_Static
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString, TCollection_HAsciiString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDimTolObjects import XCAFDimTolObjects_DimensionObject as DimObject
from OCP.XCAFDimTolObjects import XCAFDimTolObjects_DimensionType as DimType
from OCP.XCAFDoc import (
    XCAFDoc_ColorType,
    XCAFDoc_Dimension,
    XCAFDoc_DocumentTool,
    XCAFDoc_ShapeTool,
)


@dataclass
class Dim:
    """A dimension to write: its kind, stated value and tolerance, and the faces it refers to."""

    kind: str  # "distance" between the two X faces of the box, or "diameter" of the hole
    value: float
    tol: float = 0.1


@dataclass
class PartSpec:
    name: str
    shape: str = "box"  # "box" 25 x 10 x 5, or "holed" (the box with a 6 mm hole through Z)
    color: tuple[float, float, float] | None = None
    material: tuple[str, str, float] | None = None  # name, description, density number
    layer: str | None = None
    description: str | None = None
    dims: list[Dim] = field(default_factory=list)


def _shape(kind: str) -> TopoDS_Shape:
    box = BRepPrimAPI_MakeBox(25, 10, 5).Shape()
    if kind == "box":
        return box
    hole = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(12.5, 5, -1), gp_Dir(0, 0, 1)), 3.0, 7.0).Shape()
    return BRepAlgoAPI_Cut(box, hole).Shape()


def _faces(shape: TopoDS_Shape) -> list[tuple[tuple[float, float, float], object]]:
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face(ex.Current())
        g = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, g)
        c = g.CentreOfMass()
        out.append(((c.X(), c.Y(), c.Z()), f))
        ex.Next()
    return out


def _add_dimension(doc: TDocStd_Document, st: XCAFDoc_ShapeTool, label: TDF_Label, d: Dim) -> None:
    dt = XCAFDoc_DocumentTool.DimTolTool_s(doc.Main())
    stored = XCAFDoc_ShapeTool.GetShape_s(label)
    faces = _faces(stored)
    obj = DimObject()
    obj.SetValue(d.value)
    obj.SetUpperTolValue(d.tol)
    obj.SetLowerTolValue(d.tol)
    dim_label = dt.AddDimension()
    if d.kind == "distance":
        obj.SetType(DimType.XCAFDimTolObjects_DimensionType_Location_LinearDistance)
        x0 = next(f for c, f in faces if abs(c[0]) < 1e-6)
        x1 = next(f for c, f in faces if abs(c[0] - 25) < 1e-6)
        dt.SetDimension(st.AddSubShape(label, x0), st.AddSubShape(label, x1), dim_label)
    else:
        obj.SetType(DimType.XCAFDimTolObjects_DimensionType_Size_Diameter)
        # the cylindrical face of the hole: the one whose centroid sits on the hole axis
        cyl = next(
            f
            for c, f in faces
            if abs(c[0] - 12.5) < 1e-3 and abs(c[1] - 5) < 1e-3 and 0.1 < c[2] < 4.9
        )
        dt.SetDimension(st.AddSubShape(label, cyl), dim_label)
    XCAFDoc_Dimension.Set_s(dim_label).SetObject(obj)


def write_step_data_fixture(path: Path, parts: list[PartSpec]) -> Path:
    """Write a STEP file with the given parts (one free shape each) and what the specs state."""
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-CAF"))
    app.InitDocument(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    mt = XCAFDoc_DocumentTool.MaterialTool_s(doc.Main())
    lt = XCAFDoc_DocumentTool.LayerTool_s(doc.Main())
    wants_dims = False
    for spec in parts:
        label = st.AddShape(_shape(spec.shape), False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(spec.name))
        if spec.color:
            ct.SetColor(
                label,
                Quantity_Color(*spec.color, Quantity_TOC_RGB),
                XCAFDoc_ColorType.XCAFDoc_ColorGen,
            )
        if spec.material:
            name, description, density = spec.material
            ml = mt.AddMaterial(
                TCollection_HAsciiString(name),
                TCollection_HAsciiString(description),
                density,
                TCollection_HAsciiString("density"),
                TCollection_HAsciiString("g/cm3"),
            )
            mt.SetMaterial(label, ml)
        if spec.layer:
            lt.SetLayer(label, lt.AddLayer(TCollection_ExtendedString(spec.layer)))
        for d in spec.dims:
            _add_dimension(doc, st, label, d)
            wants_dims = True
    writer = STEPCAFControl_Writer()
    for mode in ("SetColorMode", "SetNameMode", "SetLayerMode", "SetPropsMode", "SetMaterialMode"):
        getattr(writer, mode)(True)
    if wants_dims:
        writer.SetDimTolMode(True)
        Interface_Static.SetCVal_s("write.step.schema", "AP242DIS")
    writer.Transfer(doc, STEPControl_AsIs)
    writer.Write(str(path))
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    text = path.read_text(encoding="latin-1")
    for spec in parts:
        if spec.description is not None:
            old = f"PRODUCT('{spec.name}','{spec.name}','',"
            assert old in text, old
            text = text.replace(old, f"PRODUCT('{spec.name}','{spec.name}','{spec.description}',")
    path.write_text(text, encoding="latin-1")
    return path
