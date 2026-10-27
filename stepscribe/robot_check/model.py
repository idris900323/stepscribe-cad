# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""A small, strict reader for URDF text: the facts the validation needs, nothing else.

Every name read from the file goes through ``clean_name`` before it is shown, and none of it is
treated as an instruction. DOCTYPE and entity declarations are refused (no entity expansion).
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np

from stepscribe.text_safety import clean_name

MAX_BYTES = 20_000_000  # a URDF larger than this is not a draft of ours
JOINT_TYPES = ("revolute", "continuous", "prismatic", "fixed", "floating", "planar")
MOVING = ("revolute", "continuous", "prismatic")


class UrdfError(ValueError):
    """The text is not a URDF that can be read at all."""


@dataclass
class Inertial:
    mass: float | None
    inertia: dict[str, float]  # ixx, ixy, ixz, iyy, iyz, izz
    origin: np.ndarray = field(default_factory=lambda: np.zeros(3))


@dataclass
class Mesh:
    filename: str
    role: str  # "visual" or "collision"


@dataclass
class Link:
    name: str
    inertial: Inertial | None
    meshes: list[Mesh]
    has_visual: bool
    has_collision: bool


@dataclass
class Limit:
    lower: float | None
    upper: float | None
    effort: float | None
    velocity: float | None


@dataclass
class Joint:
    name: str
    type: str
    parent: str | None
    child: str | None
    xyz: np.ndarray
    rpy: np.ndarray
    axis: np.ndarray
    limit: Limit | None
    bad_numbers: list[str]  # attributes that are not finite numbers


@dataclass
class Urdf:
    name: str
    links: list[Link]
    joints: list[Joint]
    duplicate_links: list[str] = field(default_factory=list)
    duplicate_joints: list[str] = field(default_factory=list)

    def link(self, name: str) -> Link | None:
        return next((x for x in self.links if x.name == name), None)


_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _floats(text: str | None, n: int, default: float, label: str, bad: list[str]) -> np.ndarray:
    if text is None:
        return np.full(n, default)
    parts = text.split()
    if len(parts) != n or not all(_NUM.match(p) for p in parts):
        bad.append(label)
        return np.full(n, default)
    vals = np.array([float(p) for p in parts])
    if not np.all(np.isfinite(vals)):
        bad.append(label)
        return np.full(n, default)
    return vals


def _num(text: str | None) -> float | None:
    if text is None or not _NUM.match(text.strip()):
        return None
    v = float(text)
    return v if math.isfinite(v) else None


def _inertial(el: ET.Element) -> Inertial:
    mass_el, inertia_el, origin_el = el.find("mass"), el.find("inertia"), el.find("origin")
    mass = _num(mass_el.get("value")) if mass_el is not None else None
    inertia: dict[str, float] = {}
    if inertia_el is not None:
        for k in ("ixx", "ixy", "ixz", "iyy", "iyz", "izz"):
            v = _num(inertia_el.get(k))
            if v is not None:
                inertia[k] = v
    xyz = _floats(origin_el.get("xyz") if origin_el is not None else None, 3, 0.0, "", [])
    return Inertial(mass, inertia, xyz)


def parse_urdf(text: str) -> Urdf:
    """Read URDF text; raises :class:`UrdfError` when it cannot be read as one."""
    if len(text.encode("utf-8", "ignore")) > MAX_BYTES:
        raise UrdfError("the file is larger than 20 MB")
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.I):
        raise UrdfError("DOCTYPE and entity declarations are not accepted")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise UrdfError(f"not well-formed XML ({exc})") from exc
    if root.tag != "robot":
        raise UrdfError(f"the root element is <{clean_name(root.tag)}>, not <robot>")
    links: list[Link] = []
    seen_links: set[str] = set()
    dup_links: list[str] = []
    for el in root.findall("link"):
        name = el.get("name") or ""
        if name in seen_links:
            dup_links.append(name)
        seen_links.add(name)
        meshes = [
            Mesh(m.get("filename") or "", role)
            for role in ("visual", "collision")
            for g in el.findall(role)
            for m in g.findall("./geometry/mesh")
        ]
        inertial_el = el.find("inertial")
        links.append(
            Link(
                name,
                _inertial(inertial_el) if inertial_el is not None else None,
                meshes,
                el.find("visual") is not None,
                el.find("collision") is not None,
            )
        )
    joints: list[Joint] = []
    seen_joints: set[str] = set()
    dup_joints: list[str] = []
    for el in root.findall("joint"):
        name = el.get("name") or ""
        if name in seen_joints:
            dup_joints.append(name)
        seen_joints.add(name)
        bad: list[str] = []
        origin, axis, lim = el.find("origin"), el.find("axis"), el.find("limit")
        parent, child = el.find("parent"), el.find("child")
        joints.append(
            Joint(
                name,
                el.get("type") or "",
                parent.get("link") if parent is not None else None,
                child.get("link") if child is not None else None,
                _floats(
                    origin.get("xyz") if origin is not None else None, 3, 0.0, "origin xyz", bad
                ),
                _floats(
                    origin.get("rpy") if origin is not None else None, 3, 0.0, "origin rpy", bad
                ),
                _floats(axis.get("xyz") if axis is not None else None, 3, 0.0, "axis xyz", bad)
                if axis is not None
                else np.array([1.0, 0.0, 0.0]),
                Limit(
                    _num(lim.get("lower")),
                    _num(lim.get("upper")),
                    _num(lim.get("effort")),
                    _num(lim.get("velocity")),
                )
                if lim is not None
                else None,
                bad,
            )
        )
    return Urdf(root.get("name") or "", links, joints, dup_links, dup_joints)


def show(name: str | None) -> str:
    """A name from the file, made safe to print: a label, never an instruction."""
    return clean_name(name or "") or "(no name)"
