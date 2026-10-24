# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""``--debug-kinematics``: why each contact was merged into one link or kept apart.

Nothing here changes the model. It reads what the kinematic builder decided (connections, links)
and writes it down next to the measured contact data, so a wrong result can be traced to the
contact or hole pair that caused it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stepscribe.assembly.contacts import part_faces as contact_faces
from stepscribe.assembly.contacts import planar_contact_detail
from stepscribe.describe.phrases import fmt
from stepscribe.geometry.properties import vec3
from stepscribe.models.schema import (
    KinContactDebug,
    KinematicModel,
    KinematicsDebug,
    KinHolePairDebug,
)

if TYPE_CHECKING:
    from stepscribe.api import Analysis
    from stepscribe.assembly.contacts import PartFaces
    from stepscribe.assembly.tree import InstanceData
    from stepscribe.understanding.kinematics import Conn, KinContext


def _pair(a: str, b: str) -> tuple[str, str]:
    lo, hi = sorted((a, b))
    return lo, hi


def _evidence_text(conn: Conn) -> str:
    return "; ".join(e.text for e in conn.evidence if e.text) or conn.kind


def _reason(
    conn: Conn | None, same_link: bool, ctx: KinContext, contact_kind: str, dist: float
) -> str:
    if conn is None:
        what = (
            f"a near miss at {fmt(dist, 2)} mm, not touching"
            if contact_kind == "near_miss"
            else f"a {contact_kind.replace('_', ' ')} contact"
        )
        return f"no connection classified for {what}" + (
            "; merged only through other connections" if same_link else "; kept as separate links"
        )
    used = any(_pair(u.a, u.b) == _pair(conn.a, conn.b) for u in ctx.soft_used)
    if conn.kind == "fixed":
        text = _evidence_text(conn)
        return f"fixed: {text}" + ("" if same_link else " (but the parts ended in different links)")
    if conn.kind == "soft":
        if used:
            return (
                "planar rest with no fasteners: treated as rigid because it was the only way to "
                "attach this part to the rest of the structure (" + _evidence_text(conn) + ")"
            )
        if same_link:
            return (
                "planar rest only; merged through other connections (" + _evidence_text(conn) + ")"
            )
        return "planar rest only; not needed to reach this part, so the links stay separate"
    return f"{conn.kind} connection kept as a joint: {_evidence_text(conn)}"


def build_debug(analysis: Analysis, model: KinematicModel, ctx: KinContext) -> KinematicsDebug:
    """Contact and hole-pair tables for the model that was built with *ctx*."""
    asm = ctx.asm
    conn_of = {_pair(c.a, c.b): c for c in ctx.conns}
    faces: dict[str, PartFaces] = {}

    def pf(inst: InstanceData) -> PartFaces:
        if inst.part_id not in faces:
            faces[inst.part_id] = contact_faces(inst.ap.geom)
        return faces[inst.part_id]

    contacts: list[KinContactDebug] = []
    for c in asm.contacts:
        a, b = ctx.by_id[c.instance_a], ctx.by_id[c.instance_b]
        conn = conn_of.get(_pair(a.id, b.id))
        la, lb = ctx.link_of.get(a.id, "?"), ctx.link_of.get(b.id, "?")
        same = la == lb
        groups = ctx.name_groups
        by_name = groups is not None and groups.same(a.id, b.id)
        cross = groups is not None and groups.differ(a.id, b.id)
        centroid = None
        if c.kind == "planar_face":
            detail = planar_contact_detail(a, b, pf(a), pf(b))
            if detail is not None:
                centroid = vec3(detail[2])
        contacts.append(
            KinContactDebug(
                id=c.id,
                instance_a=a.id,
                instance_b=b.id,
                name_a=a.name,
                name_b=b.name,
                kind=c.kind,
                area_mm2=c.contact_area_mm2,
                normal=c.normal,
                centroid=centroid,
                distance_mm=c.min_distance_mm,
                connection=conn.kind if conn else "none",
                link_a=la,
                link_b=lb,
                decision="merged" if same else "separate",
                reason=(
                    f"same link by name pattern ({groups.group_of[a.id]}, confidence {fmt(groups.confidence, 2)})"
                    if by_name and groups is not None
                    else _reason(conn, same, ctx, c.kind, c.min_distance_mm)
                    + (
                        f" [different link groups {groups.group_of[a.id]} / {groups.group_of[b.id]}: never merged by contact alone]"
                        if cross and groups is not None and conn is None
                        else ""
                    )
                ),
            )
        )
    pairs: list[KinHolePairDebug] = []
    holes = {(i.id, h.id): h for i in ctx.insts for h in i.ap.part.holes}
    for j in asm.fastener_joints:
        if j.suggested_fastener:
            continue
        effects: list[str] = []
        ids = list(j.instance_ids)
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                key = _pair(ids[x], ids[y])
                conn = conn_of.get(key)
                same = ctx.link_of.get(key[0]) == ctx.link_of.get(key[1])
                n0, n1 = ctx.by_id[key[0]].name, ctx.by_id[key[1]].name
                if conn is None:
                    effects.append(f"{n0} / {n1}: no connection made (the pair was ignored)")
                else:
                    effects.append(
                        f"{n0} / {n1}: {conn.kind} connection ({_evidence_text(conn)}); "
                        + ("same link" if same else "different links")
                    )
        reason = j.evidence.split("; ", 1)[1] if "; " in j.evidence else j.evidence
        pairs.append(
            KinHolePairDebug(
                joint_id=j.id,
                instance_ids=ids,
                instance_names=[ctx.by_id[i].name for i in ids],
                links=[ctx.link_of.get(i, "?") for i in ids],
                hole_refs=list(j.hole_refs),
                diameters_mm=[round(holes[r].diameter_mm, 2) for r in j.hole_refs if r in holes],
                stack_thickness_mm=j.stack_thickness_mm,
                axis=j.axis,
                became_fastener=False,
                reason=reason,
                kinematic_effect=" | ".join(effects) or "none",
            )
        )
    return KinematicsDebug(contacts=contacts, hole_pairs=pairs)


def _v(v: object) -> str:
    if v is None:
        return "-"
    return f"({fmt(v.x, 2)}, {fmt(v.y, 2)}, {fmt(v.z, 2)})"  # type: ignore[attr-defined]


def debug_markdown(dbg: KinematicsDebug) -> str:
    """The debug tables as Markdown (data/kinematics_debug.md)."""
    out = [
        "# Kinematics debug",
        "",
        "Why each touching pair was merged into one link or kept as separate links. Nothing here is an",
        "analysis result; it explains the one that was produced.",
        "",
        f"## Contacts ({len(dbg.contacts)})",
        "",
        "| Contact | Pair | Kind | Area mm² | Normal | Centroid | Distance mm | Connection | Links | Decision | Reason |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in dbg.contacts:
        out.append(
            f"| {c.id} | {c.name_a} ({c.instance_a}) / {c.name_b} ({c.instance_b}) | {c.kind} | "
            f"{fmt(c.area_mm2, 1) if c.area_mm2 is not None else '-'} | {_v(c.normal)} | "
            f"{_v(c.centroid)} | {fmt(c.distance_mm, 3)} | {c.connection} | {c.link_a} / {c.link_b} | "
            f"{c.decision} | {c.reason} |"
        )
    out += [
        "",
        f"## Coaxial hole stacks that did not become a fastener ({len(dbg.hole_pairs)})",
        "",
        "| Joint | Parts | Links | Ø mm | Stack mm | Axis origin | Axis direction | Why not a fastener | What the model did |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for h in dbg.hole_pairs:
        out.append(
            f"| {h.joint_id} | {' / '.join(h.instance_names)} | {' / '.join(h.links)} | "
            f"{', '.join(fmt(d, 2) for d in h.diameters_mm)} | {fmt(h.stack_thickness_mm, 1)} | "
            f"{_v(h.axis.origin)} | {_v(h.axis.direction)} | {h.reason} | {h.kinematic_effect} |"
        )
    return "\n".join(out) + "\n"
