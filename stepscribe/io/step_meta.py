# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""What a STEP file itself states, read through OpenCASCADE's document layer (XCAF).

Product description, the material assigned to a part (name, description, density), presentation
layers and dimensions (PMI). Everything here is raw text or numbers from the file: names go through
``clean_name`` when they are stored (step_apply.py) and are labels, never instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from OCP.OCP.collections import Sequence_TDF_Label
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name, TDataStd_NamedData, TDataStd_TreeNode
from OCP.TDF import TDF_Label
from OCP.TopoDS import TopoDS_Shape
from OCP.XCAFDoc import (
    XCAFDoc,
    XCAFDoc_Dimension,
    XCAFDoc_DimTolTool,
    XCAFDoc_DocumentTool,
    XCAFDoc_LayerTool,
    XCAFDoc_Material,
    XCAFDoc_ShapeTool,
)

MAX_DIMENSIONS = 200  # per file: a model with more is not read further


@dataclass
class RawMaterial:
    name: str
    description: str | None
    density: float | None  # the number in the file; its unit is not trusted (see step_apply)


@dataclass
class RawDimension:
    kind: str  # DimType member name without the prefix, e.g. "Location_LinearDistance"
    value: float
    lower: float | None  # the lower tolerance (positive number), as stored
    upper: float | None
    faces: list[TopoDS_Shape] = field(default_factory=list)
    owner_key: str | None = None  # entry of the shape label that owns the referenced faces


@dataclass
class StepMeta:
    description: str | None = None
    material: RawMaterial | None = None
    layers: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.description is None and self.material is None and not self.layers


def _text(h: object) -> str | None:
    try:
        s = str(h.ToCString()).strip()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - an attribute that cannot be read is simply absent
        return None
    return s or None


def read_material(label: TDF_Label) -> RawMaterial | None:
    """The material assigned to the shape on *label*, if the file assigns one."""
    guid = XCAFDoc.MaterialRefGUID_s()
    if not label.IsAttribute(guid):  # FindAttribute on an absent attribute can crash the process
        return None
    node = TDataStd_TreeNode()
    if not label.FindAttribute(guid, node) or not node.HasFather():
        return None
    mat_label = node.Father().Label()
    if not mat_label.IsAttribute(XCAFDoc_Material.GetID_s()):
        return None
    attr = XCAFDoc_Material()
    if not mat_label.FindAttribute(XCAFDoc_Material.GetID_s(), attr):
        return None
    name = _text(attr.GetName())
    if not name:
        return None
    density = float(attr.GetDensity())
    return RawMaterial(name, _text(attr.GetDescription()), density if density > 0 else None)


def read_description(label: TDF_Label) -> str | None:
    """The product description of the shape on *label* (STEP ``PRODUCT`` description)."""
    if not label.IsAttribute(TDataStd_NamedData.GetID_s()):
        return None
    data = TDataStd_NamedData()
    if not label.FindAttribute(TDataStd_NamedData.GetID_s(), data):
        return None
    key = TCollection_ExtendedString("Description")
    if not data.HasString(key):
        return None
    return str(data.GetString(key).ToExtString()).strip() or None


def layer_names(doc_main: TDF_Label) -> dict[str, list[str]]:
    """Layer names by the entry of each shape label that sits on the layer."""
    tool = XCAFDoc_DocumentTool.LayerTool_s(doc_main)
    layers = Sequence_TDF_Label()
    tool.GetLayerLabels(layers)
    out: dict[str, list[str]] = {}
    for i in range(1, layers.Length() + 1):
        layer = layers.Value(i)
        if not layer.IsAttribute(TDataStd_Name.GetID_s()):
            continue
        name_attr = TDataStd_Name()
        if not layer.FindAttribute(TDataStd_Name.GetID_s(), name_attr):
            continue
        name = str(name_attr.Get().ToExtString()).strip()
        shapes = Sequence_TDF_Label()
        XCAFDoc_LayerTool.GetShapesOfLayer_s(layer, shapes)
        for j in range(1, shapes.Length() + 1):
            out.setdefault(_entry(shapes.Value(j)), []).append(name)
    return out


def _entry(label: TDF_Label) -> str:
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TDF import TDF_Tool

    entry = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, entry)
    return str(entry.ToCString())


def read_dimensions(doc_main: TDF_Label) -> list[RawDimension]:
    """Every dimension of the file with the faces it refers to (PMI)."""
    tool = XCAFDoc_DocumentTool.DimTolTool_s(doc_main)
    labels = Sequence_TDF_Label()
    tool.GetDimensionLabels(labels)
    out: list[RawDimension] = []
    for i in range(1, min(labels.Length(), MAX_DIMENSIONS) + 1):
        label = labels.Value(i)
        try:
            obj = XCAFDoc_Dimension.Set_s(label).GetObject()
        except Exception:  # noqa: BLE001 - a dimension that cannot be read is skipped
            continue
        first, second = Sequence_TDF_Label(), Sequence_TDF_Label()
        XCAFDoc_DimTolTool.GetRefShapeLabel_s(label, first, second)
        faces: list[TopoDS_Shape] = []
        owner: str | None = None
        for seq in (first, second):
            for j in range(1, seq.Length() + 1):
                ref = seq.Value(j)
                faces.append(XCAFDoc_ShapeTool.GetShape_s(ref))
                owner = owner or (_entry(ref.Father()) if not ref.Father().IsNull() else None)
        kind = str(obj.GetType()).rsplit("DimensionType_", 1)[-1]
        out.append(
            RawDimension(
                kind,
                float(obj.GetValue()),
                float(obj.GetLowerTolValue()),
                float(obj.GetUpperTolValue()),
                faces,
                owner,
            )
        )
    return out
