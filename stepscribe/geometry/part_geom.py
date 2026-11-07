# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""PartGeom: one solid plus everything cached about it (face table, classifier)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

import numpy as np
from OCP.TopoDS import TopoDS_Shape

from stepscribe.geometry.occ_utils import SolidClassifier, bbox_of
from stepscribe.geometry.raycast import MAX_TRIANGLES, TriMesh
from stepscribe.geometry.topology import FaceTable, build_face_table


@dataclass
class PartGeom:
    """A single-solid body analysed in its local frame."""

    name: str
    shape: TopoDS_Shape
    warnings: list[str] = field(default_factory=list)
    bores_cache: list[Any] | None = None  # filled by features.holes.find_bore_faces
    bores_warnings: list[str] = field(default_factory=list)  # raised by bores found elsewhere

    @cached_property
    def table(self) -> FaceTable:
        """Face table with stable IDs and adjacency."""
        return build_face_table(self.shape)

    @cached_property
    def vertex_neighbors(self) -> dict[int, set[int]]:
        """Face index -> the other faces that share a vertex with it (an edge neighbour shares two)."""
        from OCP.OCP.collections import (
            IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as VertexFaceMap,
        )
        from OCP.TopAbs import TopAbs_FACE, TopAbs_VERTEX
        from OCP.TopExp import TopExp

        from stepscribe.geometry.occ_utils import as_face

        vmap = VertexFaceMap()
        TopExp.MapShapesAndAncestors_s(self.shape, TopAbs_VERTEX, TopAbs_FACE, vmap)
        table = self.table
        out: dict[int, set[int]] = {i: set() for i in range(len(table.faces))}
        for k in range(1, vmap.Extent() + 1):
            idx = {table.index_of(as_face(f)) for f in vmap.FindFromIndex(k)}
            idx.discard(-1)
            for a in idx:
                out[a].update(j for j in idx if j != a)
        return out

    @cached_property
    def trimesh(self) -> TriMesh | None:
        """Triangulation for ray casting; None if the part is empty or too large to cast against."""
        from stepscribe.render.tessellate import tessellate

        mesh = tessellate(self, with_edges=False)
        if len(mesh.triangles) == 0 or len(mesh.triangles) > MAX_TRIANGLES:
            return None
        return TriMesh(mesh.vertices, mesh.triangles)

    @cached_property
    def classifier(self) -> SolidClassifier:
        """Point-in-solid classifier."""
        return SolidClassifier(self.shape)

    @cached_property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Axis-aligned bounds (min, max)."""
        return bbox_of(self.shape)

    @cached_property
    def diagonal(self) -> float:
        """Length of the bounding-box diagonal."""
        lo, hi = self.bounds
        return float(np.linalg.norm(hi - lo))
