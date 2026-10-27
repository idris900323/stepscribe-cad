# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Per-part analysis: ties readers, geometry and feature detectors into ``Part`` models.

Worker memory (`estimate_worker_mb`): a part-pool worker needs about WORKER_BASE_MB plus
WORKER_MB_PER_KFACE per thousand faces of the largest part (MB per worker). The constants come
from hardening/H3/worker_rss.py run on SO_5DOF_ARM100_Assembly.step and SO101 Assembly.step;
`worker_count` keeps the estimate under RAM_SHARE of the memory that is free.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import numpy as np
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopoDS import TopoDS_Shape

from stepscribe.features.bosses import detect_bosses
from stepscribe.features.cutouts import detect_cutouts
from stepscribe.features.fillets_chamfers import detect_chamfers, detect_fillets
from stepscribe.features.holes import BoreResult, detect_holes
from stepscribe.features.patterns import detect_patterns
from stepscribe.features.shape_class import classify_shape
from stepscribe.features.slots_pockets import detect_pockets, detect_slots
from stepscribe.geometry.occ_utils import unique_subshapes
from stepscribe.geometry.part_geom import PartGeom
from stepscribe.geometry.properties import aabb, guess_density, mass_properties, obb
from stepscribe.geometry.thickness import sample_wall_thickness
from stepscribe.geometry.topology import topology_summary
from stepscribe.geometry.validity import is_valid_solid
from stepscribe.models.schema import (
    Boss,
    Chamfer,
    Cutout,
    CutoutPattern,
    Fillet,
    Hole,
    HolePattern,
    Part,
    Pocket,
    SemanticTag,
    ShapeClass,
    Slot,
)

T = TypeVar("T")


@dataclass
class AnalyzeOptions:
    """User-facing options shared by the API, CLI and MCP server."""

    density: float | None = None
    material: str | None = None
    up: str = "+Z"
    front: str = "-Y"
    no_timestamp: bool = False
    check_interference: bool = False
    skip_wall_thickness: bool = False
    understanding: bool = True
    check_motion: bool = False
    motion_budget_s: int = 120
    debug_graphs: bool = False
    debug_kinematics: bool = False
    pivot_min_diameter_mm: float | None = None  # None: roles.yaml (kinematics.pivot)
    pivot_min_length_ratio: float | None = None
    precision: int = 4
    extra: dict[str, Any] = field(default_factory=dict)


def split_bodies(name: str, shape: TopoDS_Shape) -> list[tuple[str, TopoDS_Shape]]:
    """One part per solid; several solids become ``<name>_body<n>`` (stable order)."""
    solids = unique_subshapes(shape, TopAbs_SOLID)
    if len(solids) <= 1:
        return [(name, solids[0] if solids else shape)]
    keyed = []
    for s in solids:
        bb = aabb(s)
        keyed.append(
            ((round(bb.min.x, 3), round(bb.min.y, 3), round(bb.min.z, 3), round(bb.size.x, 3)), s)
        )
    keyed.sort(key=lambda kv: kv[0])
    return [(f"{name}_body{i}", s) for i, (_k, s) in enumerate(keyed, 1)]


def _guarded(label: str, default: T, warnings: list[str], fn: Callable[[], T]) -> T:
    """Rule 11: per-entity errors become warnings, never tracebacks."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"{label} failed: {type(exc).__name__}: {exc}")
        return default


def content_hash(part: Part) -> str:
    """Hash of rounded volume, area, OBB sizes, face-type counts and sorted hole diameters."""
    parts = [
        f"{part.mass.volume_mm3:.2f}",
        f"{part.mass.surface_area_mm2:.2f}",
        *(f"{s:.2f}" for s in part.obb.size_sorted),
        *(f"{k}={v}" for k, v in sorted(part.topology.face_types.items())),
        *(f"{d:.3f}" for d in sorted(h.diameter_mm for h in part.holes)),
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]  # noqa: S324


@dataclass
class AnalyzedPart:
    """A ``Part`` plus the live geometry that produced it (needed for assembly analysis)."""

    part: Part
    geom: PartGeom


def analyze_geom(
    geom: PartGeom,
    source_file: str,
    opts: AnalyzeOptions,
    color: list[float] | None = None,
    semantics: Callable[[PartGeom, Part], list[SemanticTag]] | None = None,
) -> Part:
    """Run every analysis step on one solid. Failures become warnings on the part."""
    shape = geom.shape
    w: list[str] = []
    solid = is_valid_solid(shape)
    if not solid:
        w.append("shape is not a valid closed solid; results may be unreliable")
    material = opts.extra.get("part_materials", {}).get(geom.name) or opts.material
    density = opts.density
    if density is None and material:
        guess = guess_density(material)
        if guess is not None:
            density = guess[0]
        else:
            w.append(f"material '{material}' is not a known keyword; mass left unknown")
    mass = mass_properties(shape, geom.name, density, material)
    topo = topology_summary(shape, geom.table)
    bb, ob = aabb(shape), obb(shape)
    holes: list[Hole] = _guarded("hole detection", [], w, lambda: detect_holes(geom))
    patterns: list[HolePattern] = _guarded(
        "pattern detection", [], w, lambda: detect_patterns(holes)
    )
    no_slots: tuple[list[Slot], set[str]] = ([], set())
    slots_used = _guarded("slot detection", no_slots, w, lambda: detect_slots(geom))
    slots, slot_faces = slots_used
    fillets: list[Fillet] = _guarded(
        "fillet detection", [], w, lambda: detect_fillets(geom, slot_faces)
    )
    chamfers: list[Chamfer] = _guarded("chamfer detection", [], w, lambda: detect_chamfers(geom))
    bosses: list[Boss] = _guarded("boss detection", [], w, lambda: detect_bosses(geom, holes))
    pockets: list[Pocket] = _guarded("pocket detection", [], w, lambda: detect_pockets(geom, holes))
    wall = None
    if not opts.skip_wall_thickness:
        wall = _guarded("wall thickness", None, w, lambda: sample_wall_thickness(geom))
    shape_class: ShapeClass = _guarded(
        "shape classification",
        ShapeClass(confidence=0.0, evidence="classification failed", label="other"),
        w,
        lambda: classify_shape(geom, ob, mass.volume_mm3, mass.surface_area_mm2, holes, wall),
    )
    part = Part(
        id="",
        name=geom.name,
        source_file=source_file,
        content_hash="",
        is_valid_solid=solid,
        bbox=bb,
        obb=ob,
        mass=mass,
        topology=topo,
        shape_class=shape_class,
        holes=holes,
        hole_patterns=patterns,
        fillets=fillets,
        chamfers=chamfers,
        bosses=bosses,
        slots=slots,
        pockets=pockets,
        color_rgb=color,
        min_wall_thickness_mm=wall[0] if wall else None,
        warnings=[*geom.warnings, *w],
    )
    no_cutouts: tuple[list[Cutout], list[CutoutPattern]] = ([], [])
    part.cutouts, part.cutout_patterns = _guarded(
        "cutout detection", no_cutouts, part.warnings, lambda: detect_cutouts(geom, part)
    )
    if semantics is not None:
        part.semantic_tags = _guarded(
            "semantic matching", [], part.warnings, lambda: semantics(geom, part)
        )
    if opts.understanding:
        from stepscribe.understanding import part_understanding

        override = opts.extra.get("part_processes", {}).get(geom.name) or opts.extra.get(
            "default_process"
        )
        part.understanding = _guarded(
            "understanding", None, part.warnings, lambda: part_understanding(geom, part, override)
        )
    part.content_hash = content_hash(part)
    return part


_chunk_part: list[tuple[str, PartGeom]] = []  # the one part this worker last cast rays for


def _load_geom(brep_path: str, name: str) -> PartGeom:
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools

    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, brep_path, BRep_Builder()):
        raise RuntimeError(f"could not reload part '{name}' for parallel analysis")
    return PartGeom(name, shape)


def bore_chunk(brep_path: str, name: str, lo: int, hi: int) -> list[BoreResult]:
    """Pool entry point: the bore results of faces ``lo..hi-1`` of a part saved as BREP.

    The ray casts of hole detection are independent per face, so the pool spreads the faces of a
    big part over its workers; :func:`stepscribe.features.holes.assemble_bores` puts them back.
    A worker keeps the part it loaded for its next chunk of the same part.
    """
    from stepscribe.features.holes import bore_candidate

    if not _chunk_part or _chunk_part[0][0] != brep_path:
        _chunk_part[:] = [(brep_path, _load_geom(brep_path, name))]
    geom = _chunk_part[0][1]
    hi = min(hi, len(geom.table.faces))
    return [r for idx in range(lo, hi) if (r := bore_candidate(geom, idx)) is not None]


def analyze_brep_file(
    brep_path: str,
    name: str,
    source_file: str,
    opts: AnalyzeOptions,
    color: list[float] | None,
    bores: tuple[list[Any], list[str]] | None = None,
) -> tuple[Part, float, list[Any] | None]:
    """Process-pool entry point: load a solid saved as BREP and analyse it.

    Returns the Part, the seconds taken and the bore faces found on the way, which the contact
    stage reuses instead of finding them again on its own copy of the shape. *bores* are the bore
    faces and warnings other workers already found for this part (see :func:`bore_chunk`).
    """
    import time

    from stepscribe.semantics import run_semantics

    started = time.time()
    _chunk_part.clear()  # this worker is about to analyse; give the memory back
    geom = _load_geom(brep_path, name)
    if bores is not None:
        geom.bores_cache, geom.bores_warnings = bores
    part = analyze_geom(geom, source_file, opts, color, run_semantics)
    return part, time.time() - started, geom.bores_cache


WORKER_BASE_MB = 340.0  # interpreter + OCC + numpy, measured 341 MB at 10 faces
WORKER_MB_PER_KFACE = 45.0  # measured about 43 MB per 1000 faces (pool worker: 383 MB at 617 faces)
RAM_SHARE = 0.6  # of the free memory that the part workers may use
_UNSET: Any = object()


def estimate_worker_mb(max_faces: int) -> float:
    """Expected peak memory of one part worker, in MB, from the face count of the largest part."""
    return WORKER_BASE_MB + WORKER_MB_PER_KFACE * max_faces / 1000.0


def available_ram_bytes(platform: str | None = None) -> int | None:
    """Free physical memory, or None if this OS does not say."""
    import os
    import sys

    try:
        if (platform or sys.platform) == "win32":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009 - Windows only
            ok = kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return int(status.ullAvailPhys) if ok else None
        sysconf = getattr(os, "sysconf")  # noqa: B009 - POSIX only
        return int(sysconf("SC_AVPHYS_PAGES")) * int(sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return None


def worker_count(
    n_parts: int,
    max_faces: int = 0,
    available_bytes: int | None = _UNSET,
    cpus: int | None = None,
    jobs: int | None = None,
) -> int:
    """Processes to use for part analysis.

    STEPSCRIBE_WORKERS wins. Otherwise CPUs - 1 (at most 8) shared between the jobs allowed to run
    at once, and never more than the free memory allows (`estimate_worker_mb`, RAM_SHARE).
    """
    import os

    from stepscribe.limits import parallelism
    from stepscribe.runner import RUNNER

    env = os.environ.get("STEPSCRIBE_WORKERS")
    if env and env.isdigit():
        return max(1, min(int(env), n_parts))
    n_jobs = max(1, jobs if jobs is not None else RUNNER.max_jobs)
    by_cpu = max(1, parallelism(cpus) // n_jobs)
    n = max(1, min(by_cpu, n_parts))
    free = available_ram_bytes() if available_bytes is _UNSET else available_bytes
    if free is not None and max_faces > 0:
        per_worker = estimate_worker_mb(max_faces) * 1024**2
        n = min(n, max(1, int(RAM_SHARE * free / (per_worker * n_jobs))))
    return n


UNKNOWN_RAM_SPLIT_WORKERS = 4  # when the OS does not say how much memory is free (macOS)


def may_split_bores(
    workers: int,
    max_faces: int,
    available_bytes: int | None = _UNSET,
    jobs: int | None = None,
) -> bool:
    """Whether the ray casts of a big part may be spread over the whole pool.

    Every worker that casts rays holds its own copy of the part, so the split puts the largest
    part into all `workers` processes at once, not into one. That is allowed when the same memory
    rule as `worker_count` (`estimate_worker_mb` for the largest part, RAM_SHARE of the free
    memory, shared between the jobs) holds for all of them. When the OS does not report free
    memory the split is used only on a pool of at most UNKNOWN_RAM_SPLIT_WORKERS processes. The
    report is the same either way: no split just means the part's own worker does all the casts.
    """
    from stepscribe.runner import RUNNER

    if workers <= 1:
        return False
    free = available_ram_bytes() if available_bytes is _UNSET else available_bytes
    if free is None:
        return workers <= UNKNOWN_RAM_SPLIT_WORKERS
    n_jobs = max(1, jobs if jobs is not None else RUNNER.max_jobs)
    per_worker = estimate_worker_mb(max_faces) * 1024**2
    return workers * per_worker * n_jobs <= RAM_SHARE * free


def assign_part_ids(parts: list[Part]) -> None:
    """PRT001... sorted by (name, content hash): Rule 6.4."""
    ordered = sorted(parts, key=lambda p: (p.name, p.content_hash))
    for i, p in enumerate(ordered, 1):
        p.id = f"PRT{i:03d}"


__all__ = [
    "AnalyzeOptions",
    "AnalyzedPart",
    "analyze_brep_file",
    "bore_chunk",
    "analyze_geom",
    "assign_part_ids",
    "may_split_bores",
    "np",
    "split_bodies",
]
