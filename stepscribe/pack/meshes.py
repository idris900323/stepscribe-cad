# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""One mesh per robot link, for a digital twin (``meshes/<link>_visual.stl``, ``..._collision.stl``).

Binary STL, SI metres, vertices in the link's own frame: the frame of robot.urdf, which sits on the
origin of the joint that carries the link and is parallel to the file's axes. So mesh position plus
link frame equals world position at the zero pose stored in the file.

The visual mesh is tessellated like the images (0.1 % of each part's diagonal), or coarser when a
triangle cap is given. The collision mesh is a coarser OpenCASCADE tessellation with a triangle cap:
the deflection is increased step by step until the mesh is within the cap *and* closed (no open or
non-manifold edge, consistent outward orientation, positive volume). When no step does both, the
collision mesh is the convex hull of the link (numpy only), which is closed by construction; the URDF
header and meshes/README.md say which links use it. Each part is meshed on a private copy of its
shape in one thread, so the same input gives the same bytes on every run.

A visual mesh that is not closed is reported, never hidden: when a body's source solid is not valid
and closed the note says so, otherwise it says the tessellation left the mesh open.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_FACE
from OCP.TopLoc import TopLoc_Location

from stepscribe import config, limits
from stepscribe.geometry.occ_utils import as_face, face_is_reversed, to_np, unique_subshapes
from stepscribe.geometry.validity import is_valid_solid
from stepscribe.text_safety import clean_name

if TYPE_CHECKING:
    from stepscribe.api import Analysis

DEFAULT_MAX_TRIANGLES = limits.LINK_MESH_MAX_TRIANGLES  # collision mesh of one link
MIN_TRIANGLES = 12  # a box: the smallest mesh the cap can ask for
MM = 1e-3
# (deflection as a share of the link's diagonal, angular deflection in rad), finest first
COARSE_STEPS = ((0.01, 0.5), (0.02, 0.8), (0.04, 0.8), (0.08, 1.2), (0.16, 1.5), (0.32, 2.0))
VISUAL_STEPS = ((0.002, 0.3), (0.004, 0.4), (0.008, 0.5), (0.016, 0.6)) + COARSE_STEPS
HULL_MAX_POINTS = 800  # directions sampled for the hull of a big link
WELD = 1e-6  # m: vertices closer than this are one vertex when edges are counted
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)}
_RESERVED |= {f"LPT{i}" for i in range(1, 10)}
_STL = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
Mesh = tuple[np.ndarray, np.ndarray]  # vertices (N, 3), triangles (M, 3)


@dataclass
class MeshHealth:
    """Closedness of a mesh: edges are counted per body shell with vertices welded at 1 micrometre."""

    triangles: int
    open_edges: int
    non_manifold_edges: int
    flipped_edges: int  # an edge walked twice in the same direction: inconsistent orientation
    volume_m3: float  # signed: positive when the triangles face outward

    @property
    def closed(self) -> bool:
        """No open, non-manifold or flipped edge, and a positive volume."""
        return (
            self.triangles > 0
            and self.open_edges == 0
            and self.non_manifold_edges == 0
            and self.flipped_edges == 0
            and self.volume_m3 > 0
        )


@dataclass
class LinkMeshes:
    """The files written for one link (paths are relative to the pack folder)."""

    visual: str
    collision: str
    visual_triangles: int
    collision_triangles: int
    visual_bytes: int = 0
    collision_bytes: int = 0
    collision_kind: str = "mesh"  # "mesh" (a tessellation) or "hull" (convex hull of the link)
    visual_health: MeshHealth | None = None
    collision_health: MeshHealth | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class LinkBody:
    """One placed body of a link."""

    id: str  # an ID such as INS003, never a name from the file
    part_id: str
    shape: Any
    matrix: np.ndarray  # part frame -> file frame, mm
    diagonal: float  # of the part, mm
    source_closed: bool = True  # the solid is valid and closed


@dataclass
class LinkResult:
    """Both meshes of one link, in metres and the link frame, with their health and notes."""

    visual: Mesh
    collision: Mesh
    visual_health: MeshHealth
    collision_health: MeshHealth
    collision_kind: str
    notes: list[str]


def file_stem(text: str, used: set[str]) -> str:
    """A file name stem that is safe on every OS, from text that may come from a file."""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", clean_name(text)).strip("_-")[:40].strip("_-")
    if not stem or stem.upper() in _RESERVED:
        stem = f"link_{stem}" if stem else "link"
    out, n = stem, 1
    while out.lower() in used:
        n += 1
        out = f"{stem}_{n}"
    used.add(out.lower())
    return out


def link_frames(robot: dict[str, Any]) -> dict[str, np.ndarray]:
    """Origin of every link frame in the file's frame (mm): the base at 0, others on their joint."""
    frame = {robot["base_link"]: np.zeros(3)}
    for j in robot["joints"]:
        frame[j["child"]] = np.array(j["origin_mm"], dtype=float)
    return frame


def mesh_shape(shape: Any, deflection: float, angular: float) -> Mesh:
    """Triangles of *shape* (vertices (N, 3), triangles (M, 3)), meshed on a private copy."""
    copy = BRepBuilderAPI_Copy(shape, True, False).Shape()
    BRepTools.Clean_s(copy)
    BRepMesh_IncrementalMesh(copy, deflection, False, angular, False)  # one thread: stable order
    verts: list[np.ndarray] = []
    tris: list[np.ndarray] = []
    offset = 0
    for shape_face in unique_subshapes(copy, TopAbs_FACE):
        face = as_face(shape_face)
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None or tri.NbTriangles() == 0:
            continue
        trsf = loc.Transformation()
        pts = np.array([to_np(tri.Node(i).Transformed(trsf)) for i in range(1, tri.NbNodes() + 1)])
        rev = face_is_reversed(face)
        t = []
        for k in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(k).Get()
            t.append((a - 1, c - 1, b - 1) if rev else (a - 1, b - 1, c - 1))
        verts.append(pts)
        tris.append(np.array(t, dtype=int).reshape(-1, 3) + offset)
        offset += len(pts)
    if not verts:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)
    return np.vstack(verts), np.vstack(tris)


# ------------------------------------------------------------------ health
def _shell_health(vertices: np.ndarray, triangles: np.ndarray) -> tuple[int, int, int, float]:
    """(open edges, non-manifold edges, flipped edges, signed volume) of one shell."""
    if not len(triangles):
        return 0, 0, 0, 0.0
    tri = vertices[triangles]
    volume = float(np.einsum("ij,ij->", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])) / 6.0)
    _u, inverse = np.unique(np.round(vertices / WELD).astype(np.int64), axis=0, return_inverse=True)
    t = inverse.reshape(-1)[triangles]
    t = t[(t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])]
    n = int(inverse.max()) + 1
    directed = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    _k, walked = np.unique(directed[:, 0] * n + directed[:, 1], return_counts=True)
    lo, hi = directed.min(axis=1), directed.max(axis=1)
    _e, used = np.unique(lo * n + hi, return_counts=True)
    return int((used == 1).sum()), int((used > 2).sum()), int((walked > 1).sum()), volume


def mesh_health(shells: list[Mesh]) -> MeshHealth:
    """Health of a mesh made of separate body shells (each is checked on its own)."""
    rows = [_shell_health(v, t) for v, t in shells]
    return MeshHealth(
        triangles=sum(len(t) for _v, t in shells),
        open_edges=sum(r[0] for r in rows),
        non_manifold_edges=sum(r[1] for r in rows),
        flipped_edges=sum(r[2] for r in rows),
        volume_m3=sum(r[3] for r in rows),
    )


# ------------------------------------------------------------------ STL
def stl_bytes(vertices: np.ndarray, triangles: np.ndarray) -> bytes:
    """Binary STL: an 80-byte header, the triangle count, then normal + 3 vertices per triangle."""
    tri = vertices[triangles] if len(triangles) else np.zeros((0, 3, 3))
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) if len(tri) else tri[:, 0]
    length = np.linalg.norm(normal, axis=1, keepdims=True) if len(tri) else normal[:, :1]
    normal = np.divide(normal, length, out=np.zeros_like(normal), where=length > 0)
    rec = np.zeros(len(tri), dtype=_STL)
    rec["n"], rec["v"] = normal, tri
    header = b"stepscribe link mesh, binary STL, metres, link frame".ljust(80, b" ")
    return header + np.uint32(len(tri)).tobytes() + rec.tobytes()


def read_stl(data: bytes) -> np.ndarray:
    """Triangles of a binary STL as an (M, 3, 3) array (used by the tests and the validator)."""
    count = int(np.frombuffer(data[80:84], dtype="<u4")[0])
    rec = np.frombuffer(data[84 : 84 + count * _STL.itemsize], dtype=_STL)
    return np.asarray(rec["v"], dtype=float)


def mesh_of_stl(data: bytes) -> Mesh:
    """An STL as (vertices, triangles); identical corners are merged by mesh_health."""
    tri = read_stl(data)
    return tri.reshape(-1, 3), np.arange(len(tri) * 3).reshape(-1, 3)


# ------------------------------------------------------------------ convex hull (numpy only)
def box_mesh(lo: np.ndarray, hi: np.ndarray) -> Mesh:
    """The 12-triangle box between two corners, outward and closed."""
    c = np.array(
        [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    )
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return c, np.array([t for a, b, d, e in quads for t in ((a, b, d), (a, d, e))], dtype=int)


def _planes(p: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = p[faces[:, 0]]
    n = np.cross(p[faces[:, 1]] - a, p[faces[:, 2]] - a)
    length = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, length, out=np.zeros_like(n), where=length > 0)
    return n, (n * a).sum(axis=1)


def _simplex(p: np.ndarray, eps: float) -> list[int] | None:
    i0 = int(np.argmin(p[:, 0]))
    d = np.linalg.norm(p - p[i0], axis=1)
    i1 = int(np.argmax(d))
    if d[i1] <= eps:
        return None
    line = p[i1] - p[i0]
    off = np.linalg.norm(np.cross(p - p[i0], line), axis=1) / np.linalg.norm(line)
    i2 = int(np.argmax(off))
    if off[i2] <= eps:
        return None
    nrm = np.cross(p[i1] - p[i0], p[i2] - p[i0])
    h = (p - p[i0]) @ (nrm / np.linalg.norm(nrm))
    i3 = int(np.argmax(np.abs(h)))
    return None if abs(h[i3]) <= eps else [i0, i1, i2, i3]


def _hull(p: np.ndarray) -> Mesh | None:
    """Quickhull-style incremental hull: always add the farthest point outside the current hull."""
    scale = float(np.ptp(p, axis=0).max())
    eps = 1e-9 * max(scale, 1e-9)
    s = _simplex(p, eps)
    if s is None:
        return None
    inner = p[s].mean(axis=0)
    faces = np.array([[s[i] for i in f] for f in ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))])
    n, d = _planes(p, faces)
    flip = (n @ inner - d) > 0
    faces[flip] = faces[flip][:, [0, 2, 1]]
    remaining = np.array([i for i in range(len(p)) if i not in s])
    n_pts = len(p)
    for _ in range(n_pts):
        n, d = _planes(p, faces)
        if not len(remaining):
            break
        dist = p[remaining] @ n.T - d
        far = dist.max(axis=1)
        keep = far > eps
        remaining, dist, far = remaining[keep], dist[keep], far[keep]
        if not len(remaining):
            break
        k = int(np.argmax(far))
        top = int(remaining[k])
        visible = dist[k] > eps
        vis = faces[visible]
        edges = np.concatenate([vis[:, [0, 1]], vis[:, [1, 2]], vis[:, [2, 0]]])
        seen = edges[:, 0] * n_pts + edges[:, 1]
        horizon = edges[~np.isin(edges[:, 1] * n_pts + edges[:, 0], seen)]
        new = np.column_stack([horizon, np.full(len(horizon), top)])
        faces = np.vstack([faces[~visible], new])
        remaining = np.delete(remaining, k)
    used, inverse = np.unique(faces, return_inverse=True)
    return p[used], inverse.reshape(-1, 3)


def _directions(k: int) -> np.ndarray:
    i = np.arange(k) + 0.5
    phi = np.arccos(1 - 2 * i / k)
    theta = np.pi * (1 + 5**0.5) * i
    return np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1)


def convex_hull(points: np.ndarray, cap: int) -> Mesh:
    """Convex hull of *points* with at most *cap* triangles (a box when the points are flat)."""
    cap = max(MIN_TRIANGLES, int(cap))
    p = np.unique(np.round(points, 9), axis=0)
    if not len(p):
        return box_mesh(np.zeros(3), np.zeros(3))
    box = box_mesh(p.min(axis=0), p.max(axis=0))
    keep = min(cap // 2 + 2, HULL_MAX_POINTS)  # a hull of V points has 2V - 4 triangles
    if len(p) > keep:
        idx = np.unique(np.argmax(p @ _directions(keep).T, axis=0))
        p = p[idx]
    hull = _hull(p) if len(p) >= 4 else None
    if hull is None or len(hull[1]) > cap or not mesh_health([hull]).closed:
        return box
    return hull


# ------------------------------------------------------------------ one link
def _fixed(deflection: float) -> Callable[[LinkBody], float]:
    def of(_body: LinkBody) -> float:
        return deflection

    return of


def _per_part(body: LinkBody) -> float:
    return float(max(body.diagonal * config.MESH_DEFLECTION_REL, 1e-4))


class _Mesher:
    """Meshes the bodies of one link; a part placed several times is meshed once per setting."""

    def __init__(self, bodies: list[LinkBody], origin_mm: np.ndarray) -> None:
        self.bodies, self.origin = bodies, origin_mm
        self.cache: dict[tuple[str, float, float], Mesh] = {}

    def shells(self, deflection_of: Callable[[LinkBody], float], angular: float) -> list[Mesh]:
        """One (vertices in metres in the link frame, triangles) shell per body."""
        out: list[Mesh] = []
        for body in self.bodies:
            key = (body.part_id, round(deflection_of(body), 9), angular)
            if key not in self.cache:
                self.cache[key] = mesh_shape(body.shape, deflection_of(body), angular)
            v, t = self.cache[key]
            if not len(t):
                continue
            homog = np.hstack([v, np.ones((len(v), 1))])
            world = (np.asarray(body.matrix, float) @ homog.T).T[:, :3]
            out.append(((world - self.origin) * MM, t))
        return out


def _merge(shells: list[Mesh]) -> Mesh:
    if not shells:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)
    offsets = np.cumsum([0] + [len(v) for v, _t in shells[:-1]])
    verts = np.vstack([v for v, _t in shells])
    tris = np.vstack([t + o for (_v, t), o in zip(shells, offsets, strict=True)])
    return verts, tris


def _count(shells: list[Mesh]) -> int:
    return sum(len(t) for _v, t in shells)


def make_link_meshes(
    bodies: list[LinkBody],
    origin_mm: np.ndarray,
    cap: int = DEFAULT_MAX_TRIANGLES,
    visual_cap: int | None = None,
) -> LinkResult | None:
    """Visual and collision meshes of the bodies of one link, or None when nothing could be meshed."""
    cap = max(MIN_TRIANGLES, int(cap))
    mesher = _Mesher(bodies, origin_mm)
    shells = mesher.shells(_per_part, config.MESH_ANGULAR_DEFLECTION)
    if not shells:
        return None
    notes: list[str] = []
    verts = _merge(shells)[0]
    diag_mm = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0))) / MM
    if visual_cap is not None:
        visual_cap = max(MIN_TRIANGLES, int(visual_cap))
        if _count(shells) > visual_cap:
            for rel, angular in VISUAL_STEPS:
                shells = mesher.shells(_fixed(max(diag_mm * rel, 1e-3)), angular)
                if _count(shells) <= visual_cap:
                    break
            if _count(shells) > visual_cap:
                notes.append(
                    f"visual triangle cap {visual_cap} not met: {_count(shells)} triangles at the "
                    "coarsest tessellation"
                )
    visual = _merge(shells)
    visual_health = mesh_health(shells)
    if not visual_health.closed:
        h = visual_health
        if all(b.source_closed for b in bodies):
            why = "although the source solid is valid"
        else:
            open_parts = sorted({b.part_id for b in bodies if not b.source_closed})
            why = f"because the source solid is not closed ({', '.join(open_parts)})"
        notes.append(
            f"visual mesh not closed {why}: {h.open_edges} open, "
            f"{h.non_manifold_edges} non-manifold, {h.flipped_edges} flipped edges"
        )
    collision: Mesh | None = None
    collision_health: MeshHealth | None = None
    for rel, angular in COARSE_STEPS:
        cs = mesher.shells(_fixed(max(diag_mm * rel, 1e-3)), angular)
        health = mesh_health(cs)
        if 0 < health.triangles <= cap and health.closed:
            collision, collision_health = _merge(cs), health
            break
    kind = "mesh"
    if collision is None or collision_health is None:
        kind = "hull"
        collision = convex_hull(visual[0], cap)
        collision_health = mesh_health([collision])
        notes.append("collision: convex hull (no tessellation was both closed and within the cap)")
    return LinkResult(visual, collision, visual_health, collision_health, kind, notes)


def link_instances(robot: dict[str, Any]) -> dict[str, list[str]]:
    """Link ID -> instance IDs, in robot.json order."""
    return {link["id"]: [i["id"] for i in link["instances"]] for link in robot["links"]}


def _kb(n: int) -> str:
    return f"{n / 1000:.0f} kB"


def readme_text(
    robot: dict[str, Any], files: dict[str, LinkMeshes], cap: int, visual_cap: int | None
) -> str:
    """meshes/README.md: what each file is, how big it is, and what is not clean about it."""
    lines = [
        "# Link meshes",
        "",
        "Binary STL, SI metres, vertices in the link's own frame (the frame of robot.urdf: on the origin",
        "of the joint that carries the link, parallel to the file's axes). Mesh position plus link frame",
        "is the world position at the zero pose stored in the file.",
        "",
        f"Collision meshes: a coarser tessellation within {cap} triangles per link that is closed and",
        "consistently oriented; where none exists the collision mesh is the convex hull of the link.",
        "Visual meshes: " + (f"capped at {visual_cap} triangles." if visual_cap else "not capped."),
        "To make a link lighter, point its visual element in robot.urdf at its collision file.",
        "",
        "| Link | Visual triangles | Visual size | Collision triangles | Collision size | Collision |",
        "|---|---|---|---|---|---|",
    ]
    for link in robot["links"]:
        m = files.get(link["id"])
        if m is not None:
            kind = "convex hull" if m.collision_kind == "hull" else "tessellation"
            lines.append(
                f"| {link['id']} | {m.visual_triangles} | {_kb(m.visual_bytes)} | "
                f"{m.collision_triangles} | {_kb(m.collision_bytes)} | {kind} |"
            )
    notes = [(lid, n) for lid, m in files.items() for n in m.notes]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {lid}: {n}" for lid, n in notes]
    return "\n".join(lines) + "\n"


def write_link_meshes(
    analysis: Analysis,
    robot: dict[str, Any],
    folder: Path,
    max_triangles: int = DEFAULT_MAX_TRIANGLES,
    visual_max_triangles: int | None = None,
) -> dict[str, LinkMeshes]:
    """Write ``meshes/`` for every link that has geometry; return the files by link ID."""
    from stepscribe.assembly import build_instances

    cap = max(MIN_TRIANGLES, int(max_triangles))
    frames = link_frames(robot)
    placed = {i.id: i for i in build_instances(analysis)}
    out: dict[str, LinkMeshes] = {}
    used: set[str] = set()
    mesh_dir = folder / "meshes"
    for link_id, ids in link_instances(robot).items():
        bodies = [
            LinkBody(
                i,
                placed[i].ap.part.id,
                placed[i].ap.geom.shape,
                np.asarray(placed[i].matrix, dtype=float),
                placed[i].ap.geom.diagonal,
                is_valid_solid(placed[i].ap.geom.shape)
                and not any("not a valid closed solid" in w for w in placed[i].ap.part.warnings),
            )
            for i in ids
            if i in placed
        ]
        res = make_link_meshes(bodies, frames[link_id], cap, visual_max_triangles)
        if res is None:
            continue
        stem = file_stem(link_id, used)
        mesh_dir.mkdir(exist_ok=True)
        rows = {}
        for kind, (v, t) in (("visual", res.visual), ("collision", res.collision)):
            rel = f"meshes/{stem}_{kind}.stl"
            data = stl_bytes(v, t)
            (folder / rel).write_bytes(data)
            rows[kind] = (rel, len(t), len(data))
        (vrel, vn, vsize), (crel, cn, csize) = rows["visual"], rows["collision"]
        out[link_id] = LinkMeshes(
            vrel, crel, vn, cn, vsize, csize, res.collision_kind,
            res.visual_health, res.collision_health, res.notes,
        )  # fmt: skip
    if out:
        (mesh_dir / "README.md").write_text(
            readme_text(robot, out, cap, visual_max_triangles), encoding="utf-8", newline="\n"
        )
    return out
