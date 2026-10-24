# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""The kinematic headline: "Likely: 6-axis serial arm (confidence 0.89; evidence KJ1..KJ6, L0..L6)".

A headline is only a guess, so it always carries a confidence and the IDs it rests on. For a
six-joint serial arm the axes are compared with the usual layout; a match raises the confidence,
a mismatch is written out in words and lowers it. Named links without any joint evidence are
reported as "joint structure not determined", never as a static structure.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from stepscribe.features.hole_standards import load_table
from stepscribe.understanding.link_groups import numbered_groups

if TYPE_CHECKING:
    from stepscribe.assembly.tree import InstanceData
    from stepscribe.geometry.occ_utils import Vec
    from stepscribe.models.schema import KinematicModel, KinJoint


@dataclass
class Headline:
    text: str  # the one sentence
    statement: str  # the sentence plus chain facts and the pattern result
    confidence: float | None
    evidence: list[str]
    axis_pattern: list[str] = field(default_factory=list)
    is_arm: bool = False


def _cfg() -> dict:  # type: ignore[type-arg]
    return load_table("roles.yaml")["kinematics"]["arm_headline"]  # type: ignore[no-any-return]


def _unit(j: KinJoint) -> Vec:
    v = np.array([j.axis.direction.x, j.axis.direction.y, j.axis.direction.z], dtype=float)
    return v / np.linalg.norm(v)  # type: ignore[no-any-return]


def _angle(a: Vec, b: Vec) -> float:
    """Angle between two axis lines in degrees (0 to 90, direction does not matter)."""
    return math.degrees(math.acos(min(1.0, abs(float(a @ b)))))


def is_robot(model: KinematicModel) -> bool:
    """A serial arm with at least ``robot_min_joints`` revolute joints: it gets the robot interview."""
    if "serial arm" not in model.headline:
        return False
    revolute = sum(j.kind == "revolute" for j in model.joints)
    return revolute >= int(_cfg()["robot_min_joints"])


def id_range(ids: list[str]) -> str:
    """'KJ1..KJ6' when the numbers are consecutive, else the list."""
    m = [re.fullmatch(r"([A-Z]+)(\d+)", i) for i in ids]
    if len(ids) > 2 and all(m):
        nums = [int(x.group(2)) for x in m if x]
        prefix = {x.group(1) for x in m if x}
        if len(prefix) == 1 and nums == list(range(nums[0], nums[0] + len(nums))):
            return f"{ids[0]}..{ids[-1]}"
    return ", ".join(ids)


def six_axis_pattern(axes: list[Vec], up: Vec, tol: float) -> list[tuple[bool, str]]:
    """The six checks of the usual 6-axis arm layout, each as (matches, plain words)."""
    a1, a2, a3, a4, a5, a6 = axes
    out: list[tuple[bool, str]] = []

    def check(ok: bool, good: str, bad: str) -> None:
        out.append((ok, f"OK: {good}" if ok else f"DIFFERS: {bad}"))

    ang = _angle(a1, up)
    check(
        ang <= tol,
        "axis 1 is vertical",
        f"axis 1 is not vertical ({ang:.0f} degrees from the up axis)",
    )
    ang = _angle(a2, a3)
    check(
        ang <= tol,
        "axes 2 and 3 are parallel",
        f"axes 2 and 3 are not parallel ({ang:.0f} degrees apart)",
    )
    worst = max(abs(90.0 - _angle(a2, a1)), abs(90.0 - _angle(a3, a1)))
    check(
        worst <= tol,
        "axes 2 and 3 are perpendicular to axis 1",
        f"axes 2 and 3 are not both perpendicular to axis 1 (off by {worst:.0f} degrees)",
    )
    off = abs(90.0 - _angle(a4, a3))
    check(
        off <= tol,
        "axis 4 is perpendicular to axis 3",
        f"axis 4 is not perpendicular to axis 3 (off by {off:.0f} degrees)",
    )
    off = abs(90.0 - _angle(a5, a4))
    check(
        off <= tol,
        "axis 5 is perpendicular to axis 4",
        f"axis 5 is not perpendicular to axis 4 (off by {off:.0f} degrees)",
    )
    ang = _angle(a6, a4)
    check(
        ang <= tol,
        "axis 6 is parallel to axis 4",
        f"axis 6 is not parallel to axis 4 ({ang:.0f} degrees apart)",
    )
    return out


def is_serial(joints: list[KinJoint], ground: str) -> bool:
    """Each joint's child link is the next joint's parent, starting at the ground link."""
    if not joints or joints[0].parent_link != ground:
        return False
    return all(joints[i].child_link == joints[i + 1].parent_link for i in range(len(joints) - 1))


def arm_headline(
    model: KinematicModel, arm_joints: list[KinJoint], up: Vec, extras: list[str] | None = None
) -> Headline | None:
    """The headline for a serial chain of revolute joints from the ground link, else None."""
    if len(arm_joints) < 2 or any(j.kind != "revolute" for j in arm_joints):
        return None
    ground = next((g.id for g in model.links if g.is_ground), None)
    if ground is None or not is_serial(arm_joints, ground):
        return None
    cfg = _cfg()
    n = len(arm_joints)
    order = [ground] + [j.child_link for j in arm_joints]
    evidence = [id_range([j.id for j in arm_joints]), id_range(order)]
    lines: list[str] = []
    if n == 6:
        results = six_axis_pattern([_unit(j) for j in arm_joints], up, float(cfg["tolerance_deg"]))
        lines = [t for _ok, t in results]
        hits = sum(ok for ok, _t in results)
        conf = float(cfg["base_confidence"]) + float(cfg["per_match"]) * hits
        misses = len(results) - hits
        bad = [t[len("DIFFERS: ") :] for ok, t in results if not ok]
        pattern = (
            "The axis pattern matches the usual 6-axis arm layout (axis 1 vertical; axes 2 and 3 "
            "parallel and perpendicular to axis 1; axis 4 perpendicular to axis 3; axis 5 "
            "perpendicular to axis 4; axis 6 parallel to axis 4)."
            if not bad
            else "The axis pattern differs from the usual 6-axis arm layout: "
            + "; ".join(bad)
            + ". The confidence is lowered."
        )
    else:
        conf = float(cfg["other_axis_count_confidence"])
        misses = 0
        pattern = "The axis pattern is only checked for six axes."
    weakest = min(arm_joints, key=lambda j: j.confidence)
    cap = min(
        float(cfg["max_confidence"]), weakest.confidence + float(cfg["weakest_joint_headroom"])
    )
    capped = conf > cap + 1e-9
    if capped:
        conf = cap
    if n == 6:  # a mismatch still lowers a capped chain: it is subtracted after the cap
        conf -= float(cfg["per_mismatch"]) * misses
    conf = max(float(cfg["min_confidence"]), min(float(cfg["max_confidence"]), conf))
    text = f"Likely: {n}-axis serial arm (confidence {conf:.2f}; evidence {', '.join(evidence)})"
    ground_link = next(g for g in model.links if g.id == ground)
    chain = (
        f"{len(order)} links and {n} revolute joints ({model.dof} degrees of freedom) in a serial "
        f"chain from ground link {ground} ({ground_link.description}); serial order confirmed: "
        + " -> ".join(order)
        + ", each joint's child link being the next joint's parent"
        + "".join(f"; {x}" for x in extras or [])
        + "."
    )
    if capped:
        pattern += (
            f" The confidence is capped at {cap:.2f} because the weakest joint ({weakest.id}) is "
            f"only {weakest.confidence:.2f}: a matching layout does not make the joints surer."
        )
    statement = f"{text}. {chain} {pattern}"
    return Headline(text, statement, round(conf, 2), evidence, lines, is_arm=True)


def undetermined_headline(model: KinematicModel, insts: list[InstanceData]) -> Headline | None:
    """'Joint structure not determined' when parts are named LINK<n> but no joint was found."""
    if model.joints:
        return None
    groups = numbered_groups(insts)
    if len(groups) < 2:
        return None
    names = sorted(groups, key=lambda g: groups[g])
    pairs = [f"{a} and {b}" for a, b in zip(names, names[1:], strict=False)]
    text = (
        f"Joint structure not determined: parts are named {', '.join(names)} but no pivot bore, "
        f"flange or fastener evidence joins them (missing between {'; '.join(pairs)})"
    )
    statement = (
        f"{text}. The links are kept apart, not merged. Add a `kinematics:` section to "
        "design_context.yaml, or check whether the pivots are modelled."
    )
    return Headline(text, statement, None, [id_range([g.id for g in model.links])])
