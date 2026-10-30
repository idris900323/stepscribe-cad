# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Turn what the STEP file states into report data, with the precedence rules.

Precedence for the material of a part: a material the designer gave (``--material``, ``--density``,
design_context.yaml) wins; otherwise a material assigned in the file is used (``material_source:
step_file``) with the density the file states, or the one the keyword table has for its name;
otherwise nothing changes (the name guess, or no mass). Every string goes through ``clean_name`` and
is a label, never an instruction.
"""

from __future__ import annotations

import re

import numpy as np
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Face, TopoDS_Shape

from stepscribe.analysis import AnalyzeOptions
from stepscribe.geometry.occ_utils import to_np
from stepscribe.geometry.part_geom import PartGeom
from stepscribe.geometry.properties import guess_density, mass_properties
from stepscribe.geometry.surfaces import cylinder_params
from stepscribe.io.step_meta import RawDimension, RawMaterial, StepMeta
from stepscribe.models.schema import Part, PmiDimension, StepData, StepMaterial
from stepscribe.text_safety import clean_name

# A density number in a STEP file has no unit we trust. Two ranges do not overlap, so the number
# says which it is: 0.05 to 25 is g/cm3, 50 to 30000 is kg/m3. Anything else is not used.
G_CM3 = (0.05, 25.0)
KG_M3 = (50.0, 30000.0)
DEFAULT_TOL_NOTE = "no tolerance is stated, so no verdict"
LINEAR = {
    "Location_LinearDistance",
    "Location_LinearDistance_FromOuterToOuter",
    "Location_LinearDistance_FromInnerToInner",
}
CYLINDER_SIZE = {"Size_Diameter": 2.0, "Size_Radius": 1.0}
MATCH_TOL_MM = 1e-3


def density_g_cm3(value: float | None) -> float | None:
    """The density in g/cm3 for a number from the file, or None when it is not plausible."""
    if value is None:
        return None
    if G_CM3[0] <= value <= G_CM3[1]:
        return float(value)
    if KG_M3[0] <= value <= KG_M3[1]:
        return float(value) / 1000.0
    return None


def step_material(raw: RawMaterial | None) -> StepMaterial | None:
    if raw is None:
        return None
    name = clean_name(raw.name)
    if not name:
        return None
    return StepMaterial(
        name=name,
        description=clean_name(raw.description) or None,
        density_stated=raw.density,
        density_g_cm3=density_g_cm3(raw.density),
    )


def designer_gave_material(geom_name: str, opts: AnalyzeOptions) -> bool:
    return bool(
        opts.density is not None
        or opts.material
        or opts.extra.get("part_materials", {}).get(geom_name)
    )


def use_material(part: Part, geom: PartGeom, mat: StepMaterial, opts: AnalyzeOptions) -> None:
    """Set the part's mass from the file's material when no designer value outranks it."""
    if designer_gave_material(geom.name, opts):
        return
    density = mat.density_g_cm3
    if density is None:
        guess = guess_density(mat.name)  # the existing keyword table
        density = guess[0] if guess else None
    if density is None:
        return  # nothing usable: behaviour stays as it was
    part.mass = mass_properties(geom.shape, geom.name, density, mat.name, "step_file")
    mat.density_used = True


# ------------------------------------------------------------------ PMI
def _face_signature(face: TopoDS_Face) -> tuple[np.ndarray, float]:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return to_np(props.CentreOfMass()), float(props.Mass())


def match_face(face: TopoDS_Shape, geom: PartGeom) -> str | None:
    """The face ID of *geom* whose centroid and area equal those of *face*, or None."""
    if face.ShapeType() != TopAbs_FACE:
        return None
    centre, area = _face_signature(TopoDS.Face(face))
    best: tuple[float, str] | None = None
    for info in geom.table.faces:
        d = float(np.linalg.norm(info.centroid - centre))
        if d <= MATCH_TOL_MM and abs(info.area - area) <= 1e-6 * max(area, 1.0):
            if best is None or d < best[0]:
                best = (d, info.id)
    return best[1] if best else None


def _subfaces(shape: TopoDS_Shape) -> list[TopoDS_Face]:
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        out.append(TopoDS.Face(ex.Current()))
        ex.Next()
    return out


def pmi_dimension(
    n: int, raw: RawDimension, geom: PartGeom, length_unit: str
) -> PmiDimension | None:
    """One dimension of the file with its cross-check; None when it does not belong to *geom*."""
    ids = [fid for f in raw.faces if (fid := match_face(f, geom)) is not None]
    if raw.faces and not ids:
        return None  # the faces it refers to are on another body
    angular = "Angular" in raw.kind
    kind = (
        re.sub(r"(?<!^)(?=[A-Z])", "_", raw.kind.removeprefix("Location_").removeprefix("Size_"))
        .lower()
        .replace("__", "_")
    )
    dim = PmiDimension(
        id=f"PMI{n:03d}",
        kind=kind,
        stated=raw.value,
        unit="deg" if angular else "mm",
        plus=raw.upper if raw.upper else None,
        minus=raw.lower if raw.lower else None,
        face_ids=ids,
    )
    if angular or length_unit != "mm":
        dim.note = (
            "an angle is not cross-checked"
            if angular
            else f"the file's length unit is {length_unit}: not cross-checked"
        )
        return dim
    measured: float | None = None
    if raw.kind in LINEAR and len(raw.faces) == 2 and len(ids) == 2:
        dss = BRepExtrema_DistShapeShape(
            geom.table.by_id(ids[0]).face, geom.table.by_id(ids[1]).face
        )
        measured = float(dss.Value()) if dss.IsDone() else None
    elif raw.kind in CYLINDER_SIZE and len(ids) == 1:
        info = geom.table.by_id(ids[0])
        if info.kind == "cylinder":
            measured = cylinder_params(info.face).radius * CYLINDER_SIZE[raw.kind]
    if measured is None:
        dim.note = f"the dimension type {kind} is not cross-checked here"
        return dim
    dim.measured = round(measured, 4)
    if dim.plus is None and dim.minus is None:
        dim.note = DEFAULT_TOL_NOTE
        return dim
    lo = raw.value - (dim.minus or 0.0)
    hi = raw.value + (dim.plus or 0.0)
    ok = lo - 1e-6 <= measured <= hi + 1e-6
    dim.status = "within_tolerance" if ok else "outside_tolerance"
    return dim


def step_data(
    part: Part,
    geom: PartGeom,
    product_name: str | None,
    meta: StepMeta | None,
    dims: list[RawDimension],
    length_unit: str,
    opts: AnalyzeOptions,
) -> StepData | None:
    """Everything the file states about *part*; applies the material precedence as a side effect."""
    data = StepData(
        product_name=clean_name(product_name) or None,
        description=clean_name(meta.description) or None if meta else None,
        color_rgb=part.color_rgb,
        material=step_material(meta.material) if meta else None,
        layers=[x for x in (clean_name(n) for n in (meta.layers if meta else [])) if x],
    )
    for raw in dims:
        dim = pmi_dimension(len(data.dimensions) + 1, raw, geom, length_unit)
        if dim is not None:
            data.dimensions.append(dim)
    if data.material is not None:
        use_material(part, geom, data.material, opts)
    # a file that only names its parts states nothing new: the name is the part's name already
    states_something = (
        data.description or data.color_rgb or data.material or data.layers or data.dimensions
    )
    return data if states_something else None
