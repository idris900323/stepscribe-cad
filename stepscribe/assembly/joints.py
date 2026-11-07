# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Fastener joints: aligned holes across instances become one joint."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from stepscribe import config
from stepscribe.assembly.tree import InstanceData
from stepscribe.describe.phrases import fmt
from stepscribe.features.hole_standards import load_table
from stepscribe.geometry.occ_utils import Vec, canonical_dir
from stepscribe.geometry.properties import vec3
from stepscribe.models.schema import Axis, FastenerJoint, Hole

HOLE_GAP_MAX = 0.5  # mm between consecutive holes in one stack
STANDARD_LENGTHS = (4, 5, 6, 8, 10, 12, 14, 16, 20, 25, 30, 35, 40, 45, 50)
NUT_THREAD_PITCHES = 1.5  # extra screw length beyond the nut, in pitches
JOINT_CONF_FACTOR = 0.9
EXISTING_FASTENER_RADIAL = 0.1  # mm
EXISTING_FASTENER_ANGLE = 1.0  # degrees


@dataclass
class GlobalHole:
    """A hole transformed into the assembly frame."""

    inst: InstanceData
    hole: Hole
    origin: Vec
    direction: Vec  # into the material
    t0: float = 0.0
    t1: float = 0.0


def _global_holes(instances: list[InstanceData]) -> list[GlobalHole]:
    out: list[GlobalHole] = []
    for inst in instances:
        if inst.ap.part.likely_purchased_hardware:
            continue
        for h in inst.ap.part.holes:
            if h.depth_mm is None:
                continue
            o = np.array([h.axis.origin.x, h.axis.origin.y, h.axis.origin.z])
            d = np.array([h.axis.direction.x, h.axis.direction.y, h.axis.direction.z])
            out.append(GlobalHole(inst, h, inst.to_global_point(o), inst.to_global_dir(d)))
    return out


def _coaxial_groups(holes: list[GlobalHole]) -> list[list[GlobalHole]]:
    groups: list[list[GlobalHole]] = []
    for gh in holes:
        d = canonical_dir(gh.direction)
        for g in groups:
            ref = g[0]
            rd = canonical_dir(ref.direction)
            ang = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(d, rd))))))
            off = gh.origin - ref.origin
            dist = float(np.linalg.norm(off - rd * np.dot(off, rd)))
            if ang <= config.ANGULAR_TOL_DEG and dist <= config.CONTACT_TOL:
                g.append(gh)
                break
        else:
            groups.append([gh])
    return groups


def _chains(group: list[GlobalHole]) -> list[list[GlobalHole]]:
    """Split a coaxial group into stacks whose consecutive holes are <= 0.5 mm apart."""
    ref = group[0]
    d = canonical_dir(ref.direction)
    for gh in group:
        t_entry = float(np.dot(gh.origin - ref.origin, d))
        depth = gh.hole.depth_mm or 0.0
        along = float(np.dot(gh.direction, d))
        gh.t0, gh.t1 = (t_entry, t_entry + depth) if along > 0 else (t_entry - depth, t_entry)
    chains: list[list[GlobalHole]] = []
    end = -math.inf
    for gh in sorted(group, key=lambda g: (g.t0, g.inst.id)):
        if chains and gh.t0 - end <= HOLE_GAP_MAX:
            chains[-1].append(gh)
        else:
            chains.append([gh])
        end = max(end, gh.t1)
    return chains


def _round_up_length(x: float) -> int:
    for s in STANDARD_LENGTHS:
        if s >= x - 1e-9:
            return s
    return int(math.ceil(x / 10.0) * 10)


def _round_down_length(x: float) -> int | None:
    fits = [s for s in STANDARD_LENGTHS if s <= x + 1e-9]
    return fits[-1] if fits else None


def _pilot_holes(members: list[GlobalHole]) -> list[GlobalHole]:
    """Blind holes narrower than a clearance hole in the same stack: the pilot (tapping) holes.

    A Ø3.2 hole over a Ø2.6 blind hole is an M3 screw into its tapping hole, whatever size the
    narrow hole would be on its own.
    """
    clearance = [
        g.hole.diameter_mm
        for g in members
        if g.hole.is_through and any(m.fit.startswith("clearance") for m in g.hole.standard_matches)
    ]
    if not clearance:
        return []
    narrowest = min(clearance)
    return [g for g in members if not g.hole.is_through and g.hole.diameter_mm < narrowest - 1e-6]


def _designation(members: list[GlobalHole]) -> tuple[str | None, float]:
    """Screw size consistent with every hole in the stack.

    Each hole lists its top standard matches; a designation scores the sum of its best
    confidence in each hole (0 where a hole does not match it), so M3 beats M2.5 when one
    plate has Ø3.4 clearance and the other a Ø2.5 tap drill (which is also M2.5's nominal).
    A pilot hole under a clearance hole does not vote: the clearance hole names the screw.
    """
    pilots = _pilot_holes(members)
    voters = [g for g in members if g not in pilots]
    if pilots:  # only the clearance fits count
        scores = _scores(voters, clearance_only=True)
        if scores:
            des, total = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            return des, total / len(voters)
    scores = _scores(members)
    if not scores:
        return None, 0.0
    des, total = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return des, total / len(members)


def _scores(members: list[GlobalHole], clearance_only: bool = False) -> dict[str, float]:
    scores: dict[str, float] = {}
    for gh in members:
        best: dict[str, float] = {}
        for m in gh.hole.standard_matches:
            if clearance_only and not m.fit.startswith("clearance"):
                continue
            best[m.designation] = max(best.get(m.designation, 0.0), m.confidence)
        for des, c in best.items():
            scores[des] = scores.get(des, 0.0) + c
    return scores


def _suggest(
    designation: str | None, grip: float, threaded: bool, blind: bool = False
) -> tuple[str | None, str]:
    """(suggested fastener text, reasoning) following the length rule."""
    if designation is None:
        return None, "no standard screw size matches the hole diameter"
    row = load_table("screws_iso_metric.yaml")["sizes"].get(designation)
    if row is None:
        return f"{designation} screw", "length not suggested for non-metric sizes"
    if threaded:
        # A blind hole has a bottom: stop one thread pitch short so the screw does not bottom out.
        margin = float(row["pitch"]) if blind else 0.0
        length = _round_down_length(grip - margin)
        if length is None:
            return (
                f"{designation} screw",
                f"grip {fmt(grip)} mm is shorter than the shortest standard screw",
            )
        note = (
            f" less one thread pitch ({fmt(margin, 2)} mm) so it does not bottom out"
            if blind
            else ""
        )
        return (
            f"{designation} × {length} SHCS",
            f"threaded end: longest standard length not exceeding the {fmt(grip)} mm available depth{note}",
        )
    extra = float(row["nut_m"]) + NUT_THREAD_PITCHES * float(row["pitch"])
    length = _round_up_length(grip + extra)
    return (
        f"{designation} × {length} SHCS",
        f"through stack: grip {fmt(grip)} + nut {fmt(float(row['nut_m']))} + 1.5 × pitch {fmt(float(row['pitch']), 2)}, rounded up",
    )


def _existing_fastener(instances: list[InstanceData], origin: Vec, d: Vec) -> str | None:
    for inst in instances:
        part = inst.ap.part
        if not part.likely_purchased_hardware or part.shape_class.label != "fastener":
            continue
        order = np.argsort([-part.obb.half_sizes.x, -part.obb.half_sizes.y, -part.obb.half_sizes.z])
        ax = part.obb.axes[int(order[0])]
        axis = inst.to_global_dir(np.array([ax.x, ax.y, ax.z]))
        c = part.obb.center
        centre = inst.to_global_point(np.array([c.x, c.y, c.z]))
        ang = math.degrees(math.acos(max(-1.0, min(1.0, abs(float(np.dot(axis, d)))))))
        off = centre - origin
        radial = float(np.linalg.norm(off - d * np.dot(off, d)))
        if ang <= EXISTING_FASTENER_ANGLE and radial <= EXISTING_FASTENER_RADIAL:
            return inst.id
    return None


PIVOT_JOINT_CONFIDENCE = 0.5  # the stack is probably not a fastener; the kinematic stage decides


def is_pivot_size(
    diameter: float,
    length: float,
    min_diameter: float | None = None,
    min_length_ratio: float | None = None,
) -> bool:
    """A hole stack that matches no screw is a pivot candidate when it is wide and long.

    Both limits are inclusive: a Ø20 stack (the default minimum) qualifies, and so does a stack
    exactly one diameter long. Defaults come from ``roles.yaml`` (``kinematics.pivot``); the
    ``--pivot-min-diameter`` / ``--pivot-min-length-ratio`` options override them.
    """
    cfg = load_table("roles.yaml")["kinematics"]["pivot"]
    lo_d = float(cfg["min_diameter_mm"]) if min_diameter is None else min_diameter
    ratio = float(cfg["min_length_over_diameter"]) if min_length_ratio is None else min_length_ratio
    return diameter >= lo_d and length >= ratio * diameter


def stack_kind(
    diameter: float,
    length: float,
    min_diameter: float | None = None,
    min_length_ratio: float | None = None,
) -> str | None:
    """What an unmatched coaxial stack is: 'pivot', 'bore_pair' or None.

    At or above the minimum diameter a stack that matches no screw is never a fastener joint:
    long enough (:func:`is_pivot_size`) it is a pivot candidate, too short it is a large coaxial
    bore pair (a locating feature or a bearing seat). Below the minimum it is left alone.
    """
    cfg = load_table("roles.yaml")["kinematics"]["pivot"]
    lo_d = float(cfg["min_diameter_mm"]) if min_diameter is None else min_diameter
    if diameter < lo_d:
        return None
    return "pivot" if is_pivot_size(diameter, length, lo_d, min_length_ratio) else "bore_pair"


def detect_joints(
    instances: list[InstanceData],
    pivot_min_diameter: float | None = None,
    pivot_min_length_ratio: float | None = None,
) -> list[FastenerJoint]:
    """Joints between instances; IDs J001... sorted by first instance and position."""
    joints: list[tuple[tuple[object, ...], FastenerJoint]] = []
    for group in _coaxial_groups(_global_holes(instances)):
        for chain in _chains(group):
            ids = list(dict.fromkeys(gh.inst.id for gh in chain))
            if len(ids) < 2:
                continue
            ref = group[0]
            d = canonical_dir(ref.direction)
            t_lo, t_hi = min(g.t0 for g in chain), max(g.t1 for g in chain)
            grip = t_hi - t_lo
            dia = Counter(round(g.hole.diameter_mm, 2) for g in chain)
            common = sorted(dia.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            # A blind hole ends the stack: no nut can reach it and the screw must not bottom out,
            # whether or not the hole looks tapped.
            blind = any(not g.hole.is_through for g in chain)
            threaded = blind or any(g.hole.likely_threaded for g in chain)
            desig, conf = _designation(chain)
            text, why = _suggest(desig, grip, threaded, blind)
            pilots = _pilot_holes(chain)
            if pilots and desig:
                dias = ", ".join(sorted({f"Ø{fmt(g.hole.diameter_mm, 2)}" for g in pilots}))
                why += f"; the {dias} blind hole is the pilot (tapping) hole for {desig}, and the wider hole above it is its clearance hole"
                other = sorted(
                    {m.designation for g in pilots for m in g.hole.standard_matches} - {desig}
                )
                if other:
                    why += f" (on its own the pilot hole could also read as {', '.join(other)}; the mating hole decides)"
            elif blind and not any(g.hole.likely_threaded for g in chain):
                why += "; the stack ends in a blind hole that is not tap-drill size, so it needs tapping or an insert"
            origin = ref.origin + d * t_lo
            existing = _existing_fastener(instances, origin, d)
            kind = (
                stack_kind(float(common), grip, pivot_min_diameter, pivot_min_length_ratio)
                if desig is None and existing is None
                else None
            )
            pivot, bore_pair = kind == "pivot", kind == "bore_pair"
            if pivot:
                threaded = False
                conf = PIVOT_JOINT_CONFIDENCE / JOINT_CONF_FACTOR
                why = (
                    f"no standard screw size matches Ø{fmt(float(common), 2)}; a bore this wide and at "
                    "least as long as it is wide is more likely a pivot or press fit than a screw"
                )
            elif bore_pair:
                threaded = False
                conf = PIVOT_JOINT_CONFIDENCE / JOINT_CONF_FACTOR
                why = (
                    f"no standard screw size matches Ø{fmt(float(common), 2)}; a large coaxial bore pair "
                    "shorter than its diameter is a locating feature or bearing seat, not a fastener"
                )
            key = (ids[0], *(round(float(c), 2) for c in origin))
            joints.append(
                (
                    key,
                    FastenerJoint(
                        id="",
                        confidence=round(conf * JOINT_CONF_FACTOR, 2),
                        evidence=(
                            f"{len(chain)} coaxial holes across {len(ids)} parts (Ø{', Ø'.join(str(k) for k in sorted(dia))}), "
                            f"grip {fmt(grip)} mm; {why}"
                        ),
                        instance_ids=ids,
                        hole_refs=[
                            (g.inst.id, g.hole.id) for g in sorted(chain, key=lambda g: g.t0)
                        ],
                        axis=Axis(origin=vec3(origin), direction=vec3(d)),
                        common_diameter_mm=float(common),
                        stack_thickness_mm=grip,
                        suggested_fastener=text,
                        has_threaded_end=threaded,
                        existing_fastener_instance_id=existing,
                        pivot_candidate=pivot,
                        bore_pair=bore_pair,
                    ),
                )
            )
    joints.sort(key=lambda kv: kv[0])
    out = [j for _k, j in joints]
    for i, j in enumerate(out, 1):
        j.id = f"J{i:03d}"
    return out


def shopping_list(joints: list[FastenerJoint]) -> list[dict[str, object]]:
    """Aggregate screws (and nuts for through stacks) from joints that have no fastener modelled."""
    counts: Counter[str] = Counter()
    for j in joints:
        if j.existing_fastener_instance_id or not j.suggested_fastener:
            continue
        counts[j.suggested_fastener] += 1
        if not j.has_threaded_end:
            size = j.suggested_fastener.split(" ")[0]
            counts[f"{size} nut"] += 1
    return [{"item": item, "qty": qty} for item, qty in sorted(counts.items())]
