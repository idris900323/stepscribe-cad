# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Layer 1: structural checks of a URDF, with no library beyond numpy.

Valid or not is a different question from ready for a simulator (see readiness.py): a file can be
a correct tree of links and joints and still be rejected by a simulator for missing masses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from stepscribe.robot_check.findings import Finding
from stepscribe.robot_check.model import JOINT_TYPES, MOVING, Joint, Link, Urdf, show

INERTIA_TOL = 1e-9  # relative: eigenvalues at or below this share of the largest are not positive


def _err(code: str, msg: str, fix: str = "", where: str = "") -> Finding:
    return Finding(code, "error", msg, fix, where)


def check_tree(urdf: Urdf) -> list[Finding]:
    """One root, every link reachable, one parent per link, no dangling or duplicate names."""
    out: list[Finding] = []
    names = {x.name for x in urdf.links}
    if not urdf.links:
        return [_err("S010", "The file has no <link> element.", "A robot needs at least one link.")]
    for n in urdf.duplicate_links:
        out.append(
            _err(
                "S011",
                f"Link name {show(n)} is used more than once.",
                "Give each link its own name.",
                show(n),
            )
        )
    for n in urdf.duplicate_joints:
        out.append(
            _err(
                "S012",
                f"Joint name {show(n)} is used more than once.",
                "Give each joint its own name.",
                show(n),
            )
        )
    parent_of: dict[str, list[str]] = {}
    children: dict[str, list[str]] = {n: [] for n in names}
    for j in urdf.joints:
        if j.parent is None or j.child is None:
            out.append(
                _err(
                    "S013",
                    f"Joint {show(j.name)} has no <parent> or no <child>.",
                    "Add both elements.",
                    show(j.name),
                )
            )
            continue
        for role, link in (("parent", j.parent), ("child", j.child)):
            if link not in names:
                out.append(
                    _err(
                        "S014",
                        f"Joint {show(j.name)} names a {role} link {show(link)} that does not exist.",
                        "Use the name of a <link> in this file.",
                        show(j.name),
                    )
                )
        if j.parent in names and j.child in names:
            parent_of.setdefault(j.child, []).append(j.name)
            children[j.parent].append(j.child)
    for child, joints in sorted(parent_of.items()):
        if len(joints) > 1:
            listed = ", ".join(show(j) for j in joints)
            out.append(
                _err(
                    "S015",
                    f"Link {show(child)} is the child of {len(joints)} joints ({listed}): a tree gives a link one parent.",
                    "Keep one joint per child link; a closed loop cannot be written in URDF.",
                    show(child),
                )
            )
    roots = sorted(n for n in names if n not in parent_of)
    if not roots:
        out.append(
            _err(
                "S016",
                "Every link is the child of a joint, so there is no root (a cycle).",
                "Remove the joint that closes the loop.",
            )
        )
    elif len(roots) > 1:
        listed = ", ".join(show(r) for r in roots)
        out.append(
            _err(
                "S017",
                f"There are {len(roots)} root links ({listed}); a robot has exactly one.",
                "Join the separate pieces with a joint or write them as separate files.",
            )
        )
    seen: set[str] = set()
    stack = roots[:1]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack += children.get(cur, [])
    unreached = sorted(names - seen)
    if unreached and roots:
        more = " ..." if len(unreached) > 8 else ""
        listed = ", ".join(show(x) for x in unreached[:8])
        out.append(
            _err(
                "S018",
                f"{len(unreached)} link(s) cannot be reached from the root {show(roots[0])}: {listed}{more} "
                "(a cycle or a separate piece).",
                "Connect them to the root or remove the cycle.",
            )
        )
    return out


def check_joints(urdf: Urdf) -> list[Finding]:
    """Joint types, required elements, finite numbers and a usable axis."""
    out: list[Finding] = []
    for j in urdf.joints:
        w = show(j.name)
        if j.type not in JOINT_TYPES:
            out.append(
                _err(
                    "S020",
                    f"Joint {w} has the type {show(j.type)}, which URDF does not define.",
                    f"Use one of: {', '.join(JOINT_TYPES)}.",
                    w,
                )
            )
        for label in j.bad_numbers:
            out.append(
                _err(
                    "S021",
                    f"Joint {w}: {label} is not a list of finite numbers.",
                    "Write plain decimal numbers.",
                    w,
                )
            )
        if j.type in MOVING and j.type != "continuous" and j.limit is None:
            out.append(
                _err(
                    "S022",
                    f"Joint {w} is {j.type} but has no <limit> element (the URDF format requires one).",
                    "Add <limit lower=... upper=... effort=... velocity=.../>.",
                    w,
                )
            )
        lim = j.limit
        if (
            lim is not None
            and lim.lower is not None
            and lim.upper is not None
            and lim.lower > lim.upper
        ):
            out.append(
                _err(
                    "S023",
                    f"Joint {w}: the lower limit is above the upper limit.",
                    "Swap or correct the limits.",
                    w,
                )
            )
        if (j.type in MOVING or j.type == "planar") and float(np.linalg.norm(j.axis)) < 1e-9:
            out.append(
                _err(
                    "S024",
                    f"Joint {w} has an axis of zero length.",
                    "Give a non-zero axis direction.",
                    w,
                )
            )
    return out


def resolve_mesh(filename: str, base: Path) -> tuple[Path | None, str]:
    """(path of the mesh file, '') for a relative path inside *base*; else (None, why)."""
    if filename.startswith("package://"):
        return None, "package"
    if "://" in filename:
        return None, "scheme"
    p = Path(filename)
    if p.is_absolute() or filename.startswith(("/", "\\")):
        return None, "absolute"
    target = (base / p).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None, "outside"
    return target, ""


def check_meshes(urdf: Urdf, base: Path | None) -> list[Finding]:
    """Mesh files exist and stay inside the folder of the URDF (only relative paths are checked)."""
    out: list[Finding] = []
    for link in urdf.links:
        for m in link.meshes:
            where = show(link.name)
            if not m.filename:
                out.append(
                    _err(
                        "S030",
                        f"Link {where}: a <mesh> has no filename.",
                        'Add filename="meshes/<name>.stl".',
                        where,
                    )
                )
                continue
            if base is None:
                continue
            path, why = resolve_mesh(m.filename, base)
            shown = show(m.filename)
            if path is None:
                if why == "outside":
                    out.append(
                        _err(
                            "S031",
                            f"Link {where}: the {m.role} mesh path {shown} leaves the folder of the URDF.",
                            "Keep meshes in a folder next to the URDF and use a relative path.",
                            where,
                        )
                    )
                elif why == "absolute":
                    out.append(
                        Finding(
                            "S032",
                            "warning",
                            f"Link {where}: the {m.role} mesh path {shown} is absolute, so it is not "
                            "checked and breaks on another machine.",
                            "Use a path relative to the URDF.",
                            where,
                        )
                    )
                else:
                    out.append(
                        Finding(
                            "S033",
                            "warning",
                            f"Link {where}: the {m.role} mesh path {shown} needs a package or URL "
                            "resolver, so it was not checked.",
                            "Resolve it with your tool, or use a relative path.",
                            where,
                        )
                    )
            elif not path.is_file():
                out.append(
                    _err(
                        "S034",
                        f"Link {where}: the {m.role} mesh file {shown} does not exist.",
                        "Write the pack with --meshes or fix the path.",
                        where,
                    )
                )
    return out


def inertia_matrix(i: dict[str, float]) -> np.ndarray:
    ixx, iyy, izz = i.get("ixx", 0.0), i.get("iyy", 0.0), i.get("izz", 0.0)
    ixy, ixz, iyz = i.get("ixy", 0.0), i.get("ixz", 0.0), i.get("iyz", 0.0)
    return np.array([[ixx, ixy, ixz], [ixy, iyy, iyz], [ixz, iyz, izz]])


def check_inertia(link: Link) -> list[Finding]:
    """Where a link has an <inertial>: positive mass, positive-definite matrix, triangle inequality."""
    if link.inertial is None:
        return []
    w, inertial = show(link.name), link.inertial
    out: list[Finding] = []
    if inertial.mass is None or inertial.mass <= 0:
        out.append(
            _err(
                "S040",
                f"Link {w}: the mass is missing or not positive.",
                "Give a mass above zero in <mass value=.../>.",
                w,
            )
        )
    missing = [k for k in ("ixx", "iyy", "izz") if k not in inertial.inertia]
    if missing:
        out.append(
            _err(
                "S041",
                f"Link {w}: the inertia has no {', '.join(missing)}.",
                "Write all six inertia values.",
                w,
            )
        )
        return out
    eig = np.linalg.eigvalsh(inertia_matrix(inertial.inertia))
    if eig[-1] <= 0 or eig[0] <= INERTIA_TOL * eig[-1]:
        out.append(
            _err(
                "S042",
                f"Link {w}: the inertia matrix is not positive definite (smallest principal moment {eig[0]:.3g}).",
                "Recompute the inertia from a real mass distribution; a flat or negative value cannot exist.",
                w,
            )
        )
    elif eig[0] + eig[1] < eig[2] * (1 - 1e-9):
        out.append(
            _err(
                "S043",
                f"Link {w}: the principal moments break the triangle inequality (the two smaller add up to less than the largest).",
                "A rigid body cannot have these moments; recompute them.",
                w,
            )
        )
    return out


def check_against_robot_json(urdf: Urdf, robot: dict[str, Any]) -> list[Finding]:
    """The URDF has the joints robot.json lists, with the same parents, children and kinds."""
    out: list[Finding] = []
    by_name = {j.name: j for j in urdf.joints}
    listed = robot.get("joints", [])
    if len(listed) != len(urdf.joints):
        out.append(
            _err(
                "S050",
                f"robot.json lists {len(listed)} joints and the URDF has {len(urdf.joints)}.",
                "Write the URDF again from the same pack.",
            )
        )
    for j in listed:
        name = f"joint_{j.get('id')}"
        u: Joint | None = by_name.get(name)
        w = show(name)
        if u is None:
            out.append(
                _err(
                    "S051",
                    f"robot.json lists joint {show(str(j.get('id')))} but the URDF has no joint {w}.",
                    "Write the URDF again from the same pack.",
                    w,
                )
            )
            continue
        kind = j.get("type")
        if not (u.type == kind or (kind == "revolute" and u.type == "continuous")):
            out.append(
                _err(
                    "S052",
                    f"Joint {w} is {show(u.type)} in the URDF and {show(str(kind))} in robot.json.",
                    "Write the URDF again from the same pack.",
                    w,
                )
            )
        if (u.parent, u.child) != (j.get("parent"), j.get("child")):
            out.append(
                _err(
                    "S053",
                    f"Joint {w} joins {show(u.parent)} to {show(u.child)} in the URDF but "
                    f"{show(str(j.get('parent')))} to {show(str(j.get('child')))} in robot.json.",
                    "Write the URDF again from the same pack.",
                    w,
                )
            )
    return out


def structural_checks(urdf: Urdf, base: Path | None, robot: dict[str, Any] | None) -> list[Finding]:
    out = check_tree(urdf) + check_joints(urdf) + check_meshes(urdf, base)
    for link in urdf.links:
        out += check_inertia(link)
    if robot is not None:
        out += check_against_robot_json(urdf, robot)
    return out
