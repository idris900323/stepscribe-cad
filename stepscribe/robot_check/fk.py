# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Forward kinematics of a URDF in plain numpy: stepscribe's own answer, to cross-check a library."""

from __future__ import annotations

import math

import numpy as np

from stepscribe.robot_check.model import MOVING, Joint, Urdf


def rpy_matrix(rpy: np.ndarray) -> np.ndarray:
    """URDF roll-pitch-yaw (fixed axes x, y, z): R = Rz(yaw) Ry(pitch) Rx(roll)."""
    r, p, y = (float(v) for v in rpy)
    rx = np.array([[1, 0, 0], [0, math.cos(r), -math.sin(r)], [0, math.sin(r), math.cos(r)]])
    ry = np.array([[math.cos(p), 0, math.sin(p)], [0, 1, 0], [-math.sin(p), 0, math.cos(p)]])
    rz = np.array([[math.cos(y), -math.sin(y), 0], [math.sin(y), math.cos(y), 0], [0, 0, 1]])
    return np.asarray(rz @ ry @ rx)


def axis_rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues' formula: the rotation by *angle* (radians) about the vector *axis*."""
    a = axis / np.linalg.norm(axis)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.asarray(np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * (k @ k))


def joint_transform(joint: Joint, value: float = 0.0) -> np.ndarray:
    """The 4x4 transform from the parent link frame to the child link frame at *value*."""
    origin = np.eye(4)
    origin[:3, :3] = rpy_matrix(joint.rpy)
    origin[:3, 3] = joint.xyz
    motion = np.eye(4)
    if joint.type in ("revolute", "continuous"):
        motion[:3, :3] = axis_rotation(joint.axis, value)
    elif joint.type == "prismatic":
        motion[:3, 3] = joint.axis / np.linalg.norm(joint.axis) * value
    return np.asarray(origin @ motion)


def link_transforms(urdf: Urdf, values: dict[str, float] | None = None) -> dict[str, np.ndarray]:
    """World transform of every link reachable from the root; the root is the identity."""
    values = values or {}
    names = {x.name for x in urdf.links}
    children = {j.child for j in urdf.joints if j.child}
    roots = sorted(names - children)
    frames: dict[str, np.ndarray] = {roots[0]: np.eye(4)} if roots else {}
    pending = [j for j in urdf.joints if j.parent and j.child]
    while pending:
        moved = [j for j in pending if j.parent in frames]
        if not moved:
            break
        for j in moved:
            assert j.parent is not None and j.child is not None
            frames[j.child] = frames[j.parent] @ joint_transform(j, values.get(j.name, 0.0))
        pending = [j for j in pending if j not in moved]
    return frames


def pose_values(urdf: Urdf, n_random: int = 4, seed: int = 20260101) -> list[dict[str, float]]:
    """The zero pose, then *n_random* fixed pseudo-random poses within the limits (continuous joints
    in -pi..pi, a joint with no limit element in a small range); the same every time."""
    rng = np.random.RandomState(seed)
    moving = [j for j in urdf.joints if j.type in MOVING]
    poses: list[dict[str, float]] = [{j.name: 0.0 for j in moving}]
    for _ in range(n_random):
        pose = {}
        for j in moving:
            lo, hi = (-math.pi, math.pi) if j.type != "prismatic" else (-0.05, 0.05)
            if j.limit is not None and j.limit.lower is not None and j.limit.upper is not None:
                if j.limit.upper > j.limit.lower:
                    lo, hi = j.limit.lower, j.limit.upper
            pose[j.name] = float(rng.uniform(lo, hi))
        poses.append(pose)
    return poses


def rotation_error(a: np.ndarray, b: np.ndarray) -> float:
    """The angle in radians between two rotation matrices."""
    c = (float(np.trace(a[:3, :3].T @ b[:3, :3])) - 1.0) / 2.0
    return float(math.acos(min(1.0, max(-1.0, c))))
