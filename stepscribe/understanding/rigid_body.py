# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Rigid-body estimates from CAD volume and density: principal inertia and a static holding load.

Everything here is an estimate. The inputs are a body's mass, centre of mass and inertia about it
(from the solid's volume and an assumed or given density); nothing is measured. Lengths are mm,
masses g and inertias g*mm^2 in, torques N*m and forces N out. Gravity only: no motion, no friction,
no accelerations, rigid links.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

G = 9.80665  # m/s^2, standard gravity

STATIC_LABEL = "static holding load, gravity only, at this pose; not dynamic, not a motor selection"


@dataclass(frozen=True)
class Body:
    """Mass, centre of mass and the inertia about it, all in the same (global) axes."""

    mass_g: float
    com_mm: np.ndarray
    inertia_g_mm2: np.ndarray


@dataclass(frozen=True)
class Principal:
    """Principal moments (ascending) about the centre of mass, their axes (rows) and radii of gyration."""

    moments_g_mm2: np.ndarray
    axes: np.ndarray
    radii_mm: np.ndarray


def principal_inertia(inertia_g_mm2: np.ndarray, mass_g: float) -> Principal:
    """Eigen-decomposition of a symmetric inertia tensor: moments, right-handed unit axes, k = sqrt(I/m)."""
    tensor = np.asarray(inertia_g_mm2, dtype=float)
    tensor = (tensor + tensor.T) / 2.0
    values, vectors = np.linalg.eigh(tensor)
    axes = vectors.T.copy()
    if np.linalg.det(axes) < 0:
        axes[2] = -axes[2]
    radii = np.sqrt(np.clip(values, 0.0, None) / mass_g)
    return Principal(values, axes, radii)


def inertia_about(point_mm: np.ndarray, body: Body) -> np.ndarray:
    """The body's inertia about *point_mm* (parallel-axis theorem), in the same axes."""
    d = np.asarray(point_mm, dtype=float) - body.com_mm
    return np.asarray(
        body.inertia_g_mm2 + body.mass_g * (float(d @ d) * np.eye(3) - np.outer(d, d))
    )


def combine(bodies: list[Body]) -> Body:
    """One body from several: total mass, mass-weighted centre, inertia about that centre."""
    total = sum(b.mass_g for b in bodies)
    com = np.sum([b.mass_g * b.com_mm for b in bodies], axis=0) / total
    inertia = np.zeros((3, 3))
    for b in bodies:
        inertia += inertia_about(com, b)
    return Body(total, np.asarray(com, dtype=float), inertia)


@dataclass(frozen=True)
class JointSpec:
    id: str
    kind: str  # "revolute" or "prismatic" get a value; every other kind is not computed
    parent: str
    child: str
    origin_mm: np.ndarray  # a point on the axis, in the file's pose
    axis: np.ndarray  # the positive direction, unit length


@dataclass(frozen=True)
class Payload:
    """A mass carried at the last joint of a single chain, *offset_mm* (global axes) from its axis point."""

    mass_kg: float
    offset_mm: np.ndarray


@dataclass(frozen=True)
class JointLoad:
    joint: str
    kind: str
    value: float | None  # the load the joint must supply to hold the pose (signed about its axis)
    unit: str  # "N*m" for a revolute joint, "N" for a prismatic joint
    reason: str | None = None  # why there is no value


def _descendants(joints: list[JointSpec], root: str) -> list[str]:
    seen = [root]
    for j in joints:  # joints are ordered from the ground outward
        if j.parent in seen and j.child not in seen:
            seen.append(j.child)
    return seen


def holding_loads(
    joints: list[JointSpec],
    links: dict[str, Body | str],
    up: np.ndarray,
    payload: Payload | None = None,
) -> list[JointLoad]:
    """The static load each joint must supply to hold the pose against gravity.

    *links* maps a link ID to its body, or to a text saying why its mass is not known. A joint is
    computed only when every link beyond it has a known mass. The value is minus the gravity load
    along the joint's positive axis (a torque for a revolute joint, a force for a prismatic one), so a
    negative torque means the joint pushes against the +axis rotation the weight would cause.
    """
    gravity = -np.asarray(up, dtype=float) / np.linalg.norm(up) * G
    chain = all(joints[i].child == joints[i + 1].parent for i in range(len(joints) - 1))
    out: list[JointLoad] = []
    for j in joints:
        unit = "N" if j.kind == "prismatic" else "N*m"
        if j.kind not in ("revolute", "prismatic"):
            out.append(JointLoad(j.id, j.kind, None, unit, f"not computed: {j.kind} joint"))
            continue
        if payload is not None and not chain:
            out.append(
                JointLoad(
                    j.id,
                    j.kind,
                    None,
                    unit,
                    "not computed: a payload needs a single chain of joints "
                    "(the point it is carried at is not defined for a branched model)",
                )
            )
            continue
        below = _descendants(joints, j.child)
        unknown = [lid for lid in below if not isinstance(links.get(lid), Body)]
        if unknown:
            why = []
            for lid in unknown:
                cause = links.get(lid)
                why.append(
                    f"{lid}: {cause.removeprefix('not computed: ')}"
                    if isinstance(cause, str)
                    else lid
                )
            out.append(
                JointLoad(
                    j.id,
                    j.kind,
                    None,
                    unit,
                    "not computed: mass unknown or unreliable (link " + "; ".join(why) + ")",
                )
            )
            continue
        axis = np.asarray(j.axis, dtype=float)
        origin = np.asarray(j.origin_mm, dtype=float) / 1000.0
        force = np.zeros(3)
        moment = np.zeros(3)
        loads: list[tuple[float, np.ndarray]] = [
            (links[lid].mass_g / 1000.0, links[lid].com_mm / 1000.0)  # type: ignore[union-attr]
            for lid in below
        ]
        if payload is not None:
            tip = np.asarray(joints[-1].origin_mm, dtype=float) + np.asarray(
                payload.offset_mm, dtype=float
            )
            loads.append((payload.mass_kg, tip / 1000.0))
        for mass_kg, point in loads:
            f = mass_kg * gravity
            force += f
            moment += np.cross(point - origin, f)
        load = float(axis @ force) if j.kind == "prismatic" else float(axis @ moment)
        out.append(JointLoad(j.id, j.kind, -load + 0.0, unit))
    return out
