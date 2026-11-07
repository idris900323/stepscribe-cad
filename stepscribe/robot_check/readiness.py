# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Simulator readiness: what a physics simulator would reject or do oddly with a valid URDF.

Kept apart from structural validity on purpose. The words say what usually happens and what to
change; they describe common simulators in general, not one product's current version.
"""

from __future__ import annotations

from stepscribe.robot_check.findings import Finding
from stepscribe.robot_check.model import MOVING, Urdf, show

TINY_MASS_KG = 1e-6


def readiness_checks(urdf: Urdf) -> list[Finding]:
    out: list[Finding] = []
    children = {j.child for j in urdf.joints if j.child}
    for link in urdf.links:
        if link.inertial is None:
            root = link.name not in children and len(urdf.links) > 1
            out.append(
                Finding(
                    "R001",
                    "info" if root else "warning",
                    f"Link {show(link.name)} has no <inertial>. "
                    + (
                        "A fixed root is usually fine."
                        if root
                        else "Many simulators give it no mass or refuse to load a moving body without one, "
                        "so it falls, flies or is rejected."
                    ),
                    "Add <inertial> with a mass and an inertia (the CAD estimate, or measured).",
                    show(link.name),
                )
            )
    for j in urdf.joints:
        if j.type == "continuous":
            out.append(
                Finding(
                    "R002",
                    "warning",
                    f"Joint {show(j.name)} is continuous (no limits known): it can turn without end, so a "
                    "controller or a collision check has nothing to stop it.",
                    "Set the real range and write the joint as revolute with <limit lower upper>.",
                    show(j.name),
                )
            )
        lim = j.limit
        if (
            j.type in MOVING
            and lim is not None
            and ((lim.effort or 0) == 0 or (lim.velocity or 0) == 0)
        ):
            out.append(
                Finding(
                    "R003",
                    "warning",
                    f"Joint {show(j.name)} has effort or velocity 0 in its <limit>: some simulators read 0 as "
                    "'no force allowed' (the joint cannot move), others as 'no limit'; either way it is not the "
                    "real drive value.",
                    "Set the real effort (N or N*m) and velocity (m/s or rad/s) of the drive.",
                    show(j.name),
                )
            )
    for link in urdf.links:
        inertial = link.inertial
        if inertial is not None and inertial.mass is not None and 0 < inertial.mass <= TINY_MASS_KG:
            out.append(
                Finding(
                    "R004",
                    "warning",
                    f"Link {show(link.name)} has a mass of {inertial.mass:.3g} kg: a near-zero mass makes the "
                    "simulation unstable.",
                    "Use a realistic mass.",
                    show(link.name),
                )
            )
    no_collision = [x for x in urdf.links if not x.has_collision]
    if no_collision:
        listed = ", ".join(show(x.name) for x in no_collision[:6]) + (
            ", ..." if len(no_collision) > 6 else ""
        )
        out.append(
            Finding(
                "R005",
                "warning",
                f"{len(no_collision)} link(s) have no <collision> geometry ({listed}): the simulator cannot "
                "detect contact for them, so they pass through each other and the floor.",
                "Write the pack with --meshes, or add <collision> by hand.",
            )
        )
    no_visual = [x for x in urdf.links if not x.has_visual]
    if no_visual:
        out.append(
            Finding(
                "R006",
                "info",
                f"{len(no_visual)} link(s) have no <visual> geometry: they are invisible in a viewer.",
                "Write the pack with --meshes.",
            )
        )
    if any(x.inertial is not None for x in urdf.links):
        out.append(
            Finding(
                "R007",
                "info",
                "Masses and inertias in a stepscribe URDF are estimates from CAD volume and an assumed "
                "density; a simulator behaves as well as those numbers are.",
                "Replace them with measured values where the behaviour matters.",
            )
        )
    return out
