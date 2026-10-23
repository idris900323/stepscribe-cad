# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""robot.json: the kinematic model as data for a robot description (a draft, never a verdict).

Built from the report alone. Lengths are mm, masses g, angles degrees, inertia g*mm^2, all in
the file's frame, with every joint at zero in the pose stored in the file. Nothing here is
measured from the real robot: masses come from CAD volume and an assumed density, and joint
limits are given only when the designer wrote them in design_context.yaml.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from stepscribe.models.schema import AxisLabel, KinJoint, Part, Report

FORMAT = "stepscribe-robot"
FORMAT_VERSION = "0.1"
LOW_FILL = 0.1  # volume / bounding-box volume below this looks like a shell, not a solid body
PARALLEL = 1e-6


def _vec(v: Any) -> np.ndarray:
    return np.array([v.x, v.y, v.z], dtype=float)


def _round(x: Any, nd: int = 6) -> Any:
    if isinstance(x, (float, np.floating)):
        return round(float(x), nd) + 0.0
    if isinstance(x, np.ndarray):
        return _round(x.tolist(), nd)
    if isinstance(x, dict):
        return {k: _round(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v, nd) for v in x]
    return x


def _up(label: AxisLabel) -> np.ndarray:
    v = np.zeros(3)
    v["XYZ".index(label[1])] = 1.0 if label[0] == "+" else -1.0
    return v


def _link_mass(report: Report, ids: list[str]) -> dict[str, Any]:
    """Mass, centre of mass and inertia about it (global axes) of the instances of one link."""
    asm = report.assembly
    assert asm is not None
    parts = {p.id: p for p in report.parts}
    by_id = {i.id: i for i in asm.instances}
    rows: list[tuple[float, np.ndarray, np.ndarray]] = []
    unknown: list[str] = []
    for iid in ids:
        inst = by_id[iid]
        part = parts[inst.part_id]
        m = part.mass.mass_g
        if m is None or part.mass.inertia_tensor_g_mm2 is None:
            unknown.append(part.name)
            continue
        rot = np.array(inst.rotation_matrix, dtype=float)
        centre = rot @ _vec(part.mass.centroid) + _vec(inst.position)
        inertia = rot @ np.array(part.mass.inertia_tensor_g_mm2, dtype=float) @ rot.T
        rows.append((m, centre, inertia))
    out: dict[str, Any] = {"mass_g": None, "com_mm": None, "inertia_g_mm2": None}
    if unknown or not rows:
        out["unknown_mass_of"] = sorted(set(unknown))
        return out
    total = sum(m for m, _, _ in rows)
    com = sum(m * c for m, c, _ in rows) / total
    inertia = np.zeros((3, 3))
    for m, c, i in rows:
        d = c - com
        inertia += i + m * (float(d @ d) * np.eye(3) - np.outer(d, d))
    out.update(mass_g=total, com_mm=com, inertia_g_mm2=inertia)
    return out


def _closest_points(
    p1: np.ndarray, d1: np.ndarray, p2: np.ndarray, d2: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Closest points of two lines; for parallel lines the foot of p1 on the second line."""
    n = np.cross(d1, d2)
    nn = float(n @ n)
    if nn < PARALLEL:
        return p1, p2 + d2 * float((p1 - p2) @ d2)
    r = p2 - p1
    t = float(np.cross(r, d2) @ n) / nn
    s = float(np.cross(r, d1) @ n) / nn
    return p1 + d1 * t, p2 + d2 * s


def effective_axis(j: KinJoint) -> np.ndarray:
    """The unit axis arrow of a joint as the designer's sign convention reads it.

    Positive rotation is counter-clockwise looking along the arrow toward its origin (right-hand
    rule); a joint the designer says turns the other way gets the reversed arrow.
    """
    v = _vec(j.axis.direction)
    v = v / np.linalg.norm(v)
    flipped = (j.kind == "revolute" and j.positive_direction == "cw") or (
        j.kind == "prismatic" and j.positive_direction == "-"
    )
    return -v if flipped else v  # type: ignore[no-any-return]


def _signed_angle(a: np.ndarray, b: np.ndarray, about: np.ndarray) -> float:
    return math.degrees(math.atan2(float(np.cross(a, b) @ about), float(a @ b)))


def joint_frames(
    joints: list[KinJoint], base_link: str, up: np.ndarray
) -> tuple[list[np.ndarray], list[dict[str, Any]]]:
    """Joint origins (on their own axis, at the common perpendicular to the previous axis).

    The first joint keeps its detected axis point. Later joints use the foot of the common
    perpendicular from the previous joint's axis (for parallel axes, the foot of the previous
    origin). Also the DH-style numbers between consecutive axes.
    """
    origins: list[np.ndarray] = []
    rows: list[dict[str, Any]] = []
    parent_of_link: dict[str, int] = {}
    axes = [effective_axis(j) for j in joints]
    for k, j in enumerate(joints):
        raw = _vec(j.axis.origin)
        z = axes[k]
        prev_k = parent_of_link.get(j.parent_link)
        if j.parent_link == base_link or prev_k is None:
            prev_origin, prev_axis = np.zeros(3), up
            foot_prev = prev_origin + prev_axis * float((raw - prev_origin) @ prev_axis)
            q = raw
            p = foot_prev
        else:
            prev_origin, prev_axis = origins[prev_k], axes[prev_k]
            p, q = _closest_points(prev_origin, prev_axis, raw, z)
        a = float(np.linalg.norm(q - p))
        if a > 1e-9:
            x = (q - p) / a
        else:
            cr = np.cross(prev_axis, z)
            x = cr / np.linalg.norm(cr) if float(cr @ cr) > PARALLEL else None  # type: ignore[assignment]
        alpha = 0.0 if x is None else _signed_angle(prev_axis, z, x)
        rows.append(
            {
                "joint_index": k,
                "a_mm": a,
                "alpha_deg": alpha,
                "d_mm": float((p - prev_origin) @ prev_axis),
            }
        )
        origins.append(q)
        parent_of_link[j.child_link] = k
    return origins, rows


def _limits(j: KinJoint) -> dict[str, Any]:
    unit = "mm" if j.kind == "prismatic" else "deg"
    if j.range_deg_or_mm is not None and j.range_source == "designer":
        lo, hi = j.range_deg_or_mm
        return {"lower": lo, "upper": hi, "unit": unit, "source": "design_context.yaml"}
    return {"lower": None, "upper": None, "unit": unit, "source": "unknown"}


def _shell_like(part: Part) -> bool:
    box = part.bbox
    vol = (box.max.x - box.min.x) * (box.max.y - box.min.y) * (box.max.z - box.min.z)
    return (not part.is_valid_solid) or (vol > 0 and part.mass.volume_mm3 / vol < LOW_FILL)


def build_robot(report: Report) -> dict[str, Any] | None:
    """The robot description as a dict, or None when the model has no revolute or prismatic joint."""
    u, asm = report.understanding, report.assembly
    if u is None or asm is None:
        return None
    kin = u.kinematics
    movers = [j for j in kin.joints if j.kind in ("revolute", "prismatic")]
    if not movers:
        return None
    base = next((g.id for g in kin.links if g.is_ground), kin.links[0].id)
    names = {i.id: i.path.rsplit("/", 1)[-1] for i in asm.instances}
    parts = {p.id: p for p in report.parts}
    inst_part = {i.id: i.part_id for i in asm.instances}

    links: list[dict[str, Any]] = []
    shells: list[str] = []
    for g in kin.links:
        row: dict[str, Any] = {
            "id": g.id,
            "description": g.description,
            "is_base": g.id == base,
            "instances": [{"id": i, "name": names[i]} for i in g.instance_ids],
        }
        row.update(_link_mass(report, g.instance_ids))
        row["mass_is_estimate"] = True
        low = sorted(
            {parts[inst_part[i]].name for i in g.instance_ids if _shell_like(parts[inst_part[i]])}
        )
        if low:
            row["mass_reliability"] = "low: some bodies look like hollow shells"
            shells += low
        links.append(row)

    origins, dh_rows = joint_frames(movers, base, _up(asm.up_axis))
    joints: list[dict[str, Any]] = []
    prev_origin_of_link: dict[str, np.ndarray] = {}
    for k, j in enumerate(movers):
        o = origins[k]
        parent_o = prev_origin_of_link.get(j.parent_link, np.zeros(3))
        joints.append(
            {
                "id": j.id,
                "type": j.kind,
                "parent": j.parent_link,
                "child": j.child_link,
                "axis": effective_axis(j),
                "axis_flipped": bool(float(effective_axis(j) @ _vec(j.axis.direction)) < 0.0),
                "origin_mm": o,
                "evidence_point_mm": _vec(j.axis.origin),
                "origin_in_parent_mm": o - parent_o,
                "limits": _limits(j),
                "positive_direction": j.positive_direction,
                "driven_by": j.driven_by,
                "declared_by_designer": j.declared_by_designer,
                "confidence": j.confidence,
                "evidence": [e.text for e in j.evidence],
            }
        )
        prev_origin_of_link[j.child_link] = o

    serial = (
        all(movers[i].child_link == movers[i + 1].parent_link for i in range(len(movers) - 1))
        and movers[0].parent_link == base
    )
    warnings = [
        "Masses and inertias are estimates from CAD volume and an assumed density, not measured.",
        "Vendor robot models are often hollow or simplified shells: link masses and inertias "
        "taken from them are not reliable. Check them against the datasheet before use.",
    ]
    if any(link["mass_g"] is None for link in links):
        warnings.insert(
            0,
            "No material is set, so link masses, centres of mass and inertias are unknown: pass "
            "--material or set `material:` in design_context.yaml.",
        )
    if shells:
        warnings.append(
            "These bodies look like hollow shells (volume far below their bounding box): "
            + ", ".join(sorted(set(shells)))
        )
    single = [j["id"] for j in joints if not j["declared_by_designer"] and j["confidence"] < 0.6]
    if single:
        warnings.append(
            f"The axis of {', '.join(single)} rests on one reading of the geometry; confirm it."
        )
    if any(j["limits"]["source"] == "unknown" for j in joints):
        warnings.append("Joint limits are unknown unless given in design_context.yaml.")
    data: dict[str, Any] = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "status": "DRAFT: generated from CAD geometry; needs human verification before any use",
        "source": asm.root_name,
        "units": {"length": "mm", "mass": "g", "angle": "deg", "inertia": "g*mm^2"},
        "pose_note": "all joint angles are zero in the pose stored in the file; link frames are "
        "parallel to the file's axes",
        "base_link": base,
        "links": links,
        "joints": joints,
        "dh_style": {
            "serial_chain": serial,
            "note": "a, alpha and d are measured between consecutive joint axes (the first against "
            "the up axis through the file origin); theta offsets are zero in the file pose and "
            "are not derived",
            "rows": [
                {
                    "joint": joints[r["joint_index"]]["id"],
                    **{k: v for k, v in r.items() if k != "joint_index"},
                }
                for r in dh_rows
            ]
            if serial
            else [],
        },
        "warnings": warnings,
    }
    return _round(data)  # type: ignore[no-any-return]


def robot_json(report: Report) -> str | None:
    """robot.json text (stable key order, two-space indent), or None for a non-robot."""
    data = build_robot(report)
    if data is None:
        return None
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
