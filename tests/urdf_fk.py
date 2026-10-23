"""Forward kinematics of a URDF in plain Python (numpy only): a check of the file, not a solver."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np


@dataclass
class UrdfJoint:
    name: str
    type: str
    parent: str
    child: str
    xyz: np.ndarray
    axis: np.ndarray


def parse_joints(text: str) -> list[UrdfJoint]:
    root = ET.fromstring(text)
    out = []
    for j in root.findall("joint"):
        origin, axis = j.find("origin"), j.find("axis")
        assert origin is not None and axis is not None
        assert origin.get("rpy") == "0 0 0"  # this checker only handles parallel link frames
        out.append(
            UrdfJoint(
                j.get("name") or "",
                j.get("type") or "",
                j.find("parent").get("link") or "",  # type: ignore[union-attr]
                j.find("child").get("link") or "",  # type: ignore[union-attr]
                np.array([float(x) for x in (origin.get("xyz") or "").split()]),
                np.array([float(x) for x in (axis.get("xyz") or "").split()]),
            )
        )
    return out


def rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues' formula: rotation by *angle* (radians) about the vector *axis*."""
    a = axis / np.linalg.norm(axis)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * (k @ k)  # type: ignore[no-any-return]


def world_frames(
    joints: list[UrdfJoint], base: str, angles: dict[str, float] | None = None
) -> dict[str, np.ndarray]:
    """4x4 world transform of every link; the base is the identity. Angles are by joint name."""
    angles = angles or {}
    frames = {base: np.eye(4)}
    pending = list(joints)
    while pending:
        progressed = False
        for j in list(pending):
            if j.parent in frames:
                t = np.eye(4)
                t[:3, 3] = j.xyz
                rot = np.eye(4)
                rot[:3, :3] = rotation(j.axis, angles.get(j.name, 0.0))
                frames[j.child] = frames[j.parent] @ t @ rot
                pending.remove(j)
                progressed = True
        assert progressed, "the joints do not form a tree from the base"
    return frames


def descendants(joints: list[UrdfJoint], link: str) -> set[str]:
    """The link and every link below it."""
    out = {link}
    grew = True
    while grew:
        grew = False
        for j in joints:
            if j.parent in out and j.child not in out:
                out.add(j.child)
                grew = True
    return out
