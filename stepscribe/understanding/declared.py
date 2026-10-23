# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""The designer's ``kinematics:`` section of design_context.yaml.

    kinematics:
      base: BASE                      # a link name (BASE, LINK3), a link ID (L0) or part name
      joints:
        - between: [LINK1, LINK2]     # the two links the joint connects
          type: revolute              # revolute | prismatic | cylindrical
          axis: "+Y"                  # +X..-Z or [x, y, z] in the file's frame
          origin: [150, 0, 486.5]     # optional, mm; a point on the axis
          range: [-90, 110]           # degrees (revolute) or mm (prismatic)
          positive: cw                # ccw | cw for revolute, "+" | "-" for prismatic

What is declared replaces what was detected, is marked "Confirmed by designer" and gets
confidence 1.0. Nothing in it is checked against the geometry.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from stepscribe.describe.phrases import fmt
from stepscribe.geometry.properties import vec3
from stepscribe.models.schema import Axis, Evidence, KinematicModel, KinJoint

if TYPE_CHECKING:
    from stepscribe.understanding.kinematics import KinContext

KINDS = ("revolute", "prismatic", "cylindrical")
POSITIVE = ("ccw", "cw", "+", "-")
_AXIS_WORD = re.compile(r"^([+-]?)([XYZxyz])$")


@dataclass
class DeclaredJoint:
    a: str
    b: str
    joint_id: str | None = None  # an interview answer names the joint, not its links
    kind: str | None = None
    axis: tuple[float, float, float] | None = None
    origin: tuple[float, float, float] | None = None
    range: tuple[float, float] | None = None
    positive: str | None = None


@dataclass
class Declared:
    base: str | None = None
    joints: list[DeclaredJoint] = field(default_factory=list)


def _fail(message: str) -> ValueError:
    return ValueError(f"kinematics: {message}")


def _vector(value: Any, what: str) -> tuple[float, float, float]:
    if isinstance(value, str):
        m = _AXIS_WORD.match(value.strip())
        if not m:
            raise _fail(f"{what} '{value}' is not +X, -Y, ... or [x, y, z]")
        v = [0.0, 0.0, 0.0]
        v["XYZ".index(m.group(2).upper())] = -1.0 if m.group(1) == "-" else 1.0
        return (v[0], v[1], v[2])
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise _fail(f"{what} needs three numbers, got {value!r}")
    try:
        x, y, z = (float(c) for c in value)
    except (TypeError, ValueError) as exc:
        raise _fail(f"{what} needs three numbers, got {value!r}") from exc
    return (x, y, z)


def parse_declared(ctx: dict[str, Any] | None) -> Declared:
    """The parsed section, or an empty one; a malformed entry raises ``ValueError``."""
    raw = (ctx or {}).get("kinematics")
    if not raw:
        return Declared()
    if not isinstance(raw, dict):
        raise _fail("must be a mapping with 'base' and/or 'joints'")
    out = Declared(base=str(raw["base"]) if raw.get("base") else None)
    for i, row in enumerate(raw.get("joints") or [], 1):
        if not isinstance(row, dict) or not isinstance(row.get("between"), (list, tuple)):
            raise _fail(f"joint {i} needs 'between: [linkA, linkB]'")
        if len(row["between"]) != 2:
            raise _fail(f"joint {i}: 'between' lists exactly two links")
        j = DeclaredJoint(str(row["between"][0]), str(row["between"][1]))
        if row.get("type"):
            j.kind = str(row["type"]).lower()
            if j.kind not in KINDS:
                raise _fail(f"joint {i}: type must be one of {', '.join(KINDS)}")
        if row.get("axis") is not None:
            v = np.array(_vector(row["axis"], f"joint {i} axis"))
            if float(np.linalg.norm(v)) < 1e-9:
                raise _fail(f"joint {i}: the axis is the zero vector")
            u = v / np.linalg.norm(v)
            j.axis = (float(u[0]), float(u[1]), float(u[2]))
        if row.get("origin") is not None:
            j.origin = _vector(row["origin"], f"joint {i} origin")
        if row.get("range") is not None:
            r = row["range"]
            if not isinstance(r, (list, tuple)) or len(r) != 2:
                raise _fail(f"joint {i}: range is [lower, upper]")
            try:
                lo, hi = float(r[0]), float(r[1])
            except (TypeError, ValueError) as exc:
                raise _fail(f"joint {i}: range is [lower, upper] in numbers") from exc
            j.range = (min(lo, hi), max(lo, hi))
        if row.get("positive") is not None:
            j.positive = str(row["positive"]).lower()
            if j.positive not in POSITIVE:
                raise _fail(f"joint {i}: positive must be ccw, cw, + or -")
        out.joints.append(j)
    return out


def _instance_words(kctx: KinContext, inst_id: str) -> str:
    inst = kctx.by_id[inst_id]
    return f"{inst.name} {inst.ap.part.name}".lower()


def resolve_link(token: str, model: KinematicModel, kctx: KinContext) -> str | None:
    """The link ID a name refers to: L3, a name group (LINK3, BASE) or a part-name fragment."""
    ids = {g.id.lower(): g.id for g in model.links}
    if token.lower() in ids:
        return ids[token.lower()]
    groups = kctx.name_groups
    if groups is not None:
        hits = {kctx.link_of[i] for i, g in groups.group_of.items() if g.lower() == token.lower()}
        if len(hits) == 1:
            return next(iter(hits))
    words = token.lower()
    hits = {
        kctx.link_of[i]
        for i in kctx.by_id
        if words in _instance_words(kctx, i) and i in kctx.link_of
    }
    return next(iter(hits)) if len(hits) == 1 else None


def link_token(model: KinematicModel, kctx: KinContext, link_id: str) -> str:
    """How to name a link in design_context.yaml: its name group (LINK3) when it has one."""
    groups = kctx.name_groups
    link = next((g for g in model.links if g.id == link_id), None)
    if groups is not None and link is not None:
        names = {groups.group_of.get(i) for i in link.instance_ids}
        if len(names) == 1 and None not in names:
            return str(next(iter(names)))
    return link_id


def _axis_text(d: tuple[float, float, float]) -> str | list[float]:
    v = np.array(d, dtype=float)
    v = v / np.linalg.norm(v)
    k = int(np.argmax(np.abs(v)))
    if abs(abs(float(v[k])) - 1.0) < 1e-3:
        return ("+" if v[k] > 0 else "-") + "XYZ"[k]
    return [round(float(x), 4) for x in v]


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def answers_to_kinematics(
    answers: dict[str, dict[str, Any]],
    known: dict[str, Any],
    model: KinematicModel,
    kctx: KinContext,
) -> dict[str, Any]:
    """The `kinematics:` section that the designer's answers amount to.

    Every entry written here carries ``source: [question ids]`` (``base_source`` for the base) so
    that undoing an answer can remove exactly what it wrote; entries without it are the
    designer's own and are never touched.
    """
    by_id = {j.id: j for j in model.joints}
    rows: dict[str, dict[str, Any]] = {}
    out: dict[str, Any] = {}

    def row(jid: str, qid: str) -> dict[str, Any] | None:
        j = by_id.get(jid)
        if j is None:
            return None
        r = rows.setdefault(
            jid,
            {
                "between": [
                    link_token(model, kctx, j.parent_link),
                    link_token(model, kctx, j.child_link),
                ],
                "source": [],
            },
        )
        r["source"].append(qid)
        return r

    for qid, a in sorted(answers.items()):
        q = known.get(qid)
        if q is None or a.get("status") != "answered":
            continue
        v = a.get("value")
        if q.kind == "kin_base" and isinstance(v, str) and v:
            link = next((g.id for g in model.links if g.id.lower() == v.lower()), None)
            if link is not None:
                out["base"] = link_token(model, kctx, link)
                out["base_source"] = qid
        elif q.kind == "joint_axis" and q.refs:
            j = by_id.get(q.refs[0])
            r = row(q.refs[0], qid) if j is not None else None
            if r is not None and j is not None:
                if v == "yes":
                    r["axis"] = _axis_text(
                        (j.axis.direction.x, j.axis.direction.y, j.axis.direction.z)
                    )
                elif isinstance(v, str) and v in ("X", "Y", "Z"):
                    r["axis"] = "+" + v
                else:
                    rows[q.refs[0]]["source"].remove(qid)
        elif q.kind == "joint_direction" and q.refs and v in ("ccw", "cw", "+", "-"):
            r = row(q.refs[0], qid)
            if r is not None:
                r["positive"] = v
        elif q.kind == "joint_ranges" and q.refs:
            from stepscribe.understanding.answers import parse_ranges

            for jid, lo, hi in parse_ranges(str(v), q.refs):
                r = row(jid, qid)
                if r is not None:
                    r["range"] = [lo, hi]
        elif q.kind == "joint_range" and q.refs:
            nums = _NUMBER.findall(str(v))
            r = row(q.refs[0], qid) if len(nums) >= 2 else None
            if r is not None:
                lo, hi = sorted(float(n) for n in nums[:2])
                r["range"] = [lo, hi]
    out["joints"] = [r for _jid, r in sorted(rows.items()) if len(r) > 2 or r["source"]]
    return out


def _designer(text: str) -> Evidence:
    return Evidence(code="designer", refs=[], weight=1.0, text=f"Confirmed by designer: {text}")


def _depths(model: KinematicModel, base: str) -> dict[str, int]:
    adj: dict[str, list[str]] = {g.id: [] for g in model.links}
    for j in model.joints:
        adj[j.parent_link].append(j.child_link)
        adj[j.child_link].append(j.parent_link)
    depth = {base: 0}
    q = deque([base])
    while q:
        cur = q.popleft()
        for n in sorted(adj[cur]):
            if n not in depth:
                depth[n] = depth[cur] + 1
                q.append(n)
    return depth


def _set_base(model: KinematicModel, base: str, label: str) -> None:
    for g in model.links:
        g.is_ground = g.id == base
        g.ground_evidence = [_designer(f"{label} is the base (fixed) link")] if g.is_ground else []
    depth = _depths(model, base)
    for j in model.joints:
        if depth.get(j.parent_link, 99) > depth.get(j.child_link, 99):
            j.parent_link, j.child_link = j.child_link, j.parent_link
    model.joints.sort(key=lambda j: (depth.get(j.parent_link, 99), j.id))


def apply_declared(
    model: KinematicModel, decl: Declared, kctx: KinContext | None, warnings: list[str]
) -> None:
    """Apply the designer's base and joints to *model* (links and joints change in place)."""
    if kctx is None or (decl.base is None and not decl.joints):
        return
    changed_topology = False
    if decl.base is not None:
        base = resolve_link(decl.base, model, kctx)
        if base is None:
            warnings.append(f"kinematics: no link matches the declared base '{decl.base}'")
        else:
            _set_base(model, base, decl.base)
    ground = next((g.id for g in model.links if g.is_ground), model.links[0].id)
    depth = _depths(model, ground)
    for d in decl.joints:
        if d.joint_id is not None:
            by_id = next((j for j in model.joints if j.id == d.joint_id), None)
            if by_id is not None:
                _override(by_id, d)
            continue
        la, lb = resolve_link(d.a, model, kctx), resolve_link(d.b, model, kctx)
        missing = [t for t, link in ((d.a, la), (d.b, lb)) if link is None]
        if missing or la is None or lb is None:
            warnings.append(f"kinematics: no link matches '{missing[0]}' in a declared joint")
            continue
        found = next((j for j in model.joints if {j.parent_link, j.child_link} == {la, lb}), None)
        if found is None:
            found = _new_joint(model, kctx, d, la, lb, depth)
            changed_topology = True
        _override(found, d)
    if changed_topology:
        _retopo(model, kctx)


def _override(j: KinJoint, d: DeclaredJoint) -> None:
    bits: list[str] = []
    if d.kind is not None:
        j.kind = d.kind  # type: ignore[assignment]
        bits.append(d.kind)
    if d.axis is not None:
        origin = j.axis.origin if d.origin is None else vec3(np.array(d.origin))
        j.axis = Axis(origin=origin, direction=vec3(np.array(d.axis)))
        bits.append(f"axis ({fmt(d.axis[0], 2)}, {fmt(d.axis[1], 2)}, {fmt(d.axis[2], 2)})")
    elif d.origin is not None:
        j.axis = Axis(origin=vec3(np.array(d.origin)), direction=j.axis.direction)
    if d.range is not None:
        j.range_deg_or_mm = d.range
        j.range_source = "designer"
        bits.append(f"range {d.range[0]:g} to {d.range[1]:g}")
    if d.positive is not None:
        j.positive_direction = d.positive  # type: ignore[assignment]
        bits.append(f"positive {d.positive}")
    j.declared_by_designer = True
    j.confidence = 1.0
    j.evidence = [e for e in j.evidence if e.code != "designer"] + [
        _designer(f"{j.id} " + (", ".join(bits) if bits else "exists"))
    ]
    j.description = j.description.split("; declared")[0] + "; declared by the designer"


def _new_joint(
    model: KinematicModel,
    kctx: KinContext,
    d: DeclaredJoint,
    la: str,
    lb: str,
    depth: dict[str, int],
) -> KinJoint:
    parent, child = (la, lb) if depth.get(la, 99) <= depth.get(lb, 99) else (lb, la)
    members = {g.id: g.instance_ids for g in model.links}
    centres = [
        0.5 * (kctx.by_id[i].bounds[0] + kctx.by_id[i].bounds[1]) for i in members[la] + members[lb]
    ]
    axis = np.array(d.axis if d.axis is not None else (0.0, 0.0, 1.0))
    origin = np.array(d.origin) if d.origin is not None else np.mean(centres, axis=0)
    n = len(model.joints) + 1
    j = KinJoint(
        id=f"KJ{n}",
        kind=(d.kind or "revolute"),
        parent_link=parent,
        child_link=child,
        axis=Axis(origin=vec3(origin), direction=vec3(axis)),
        evidence=[],
        confidence=1.0,
        description=f"KJ{n} declared by the designer between {parent} and {child}",
    )
    model.joints.append(j)
    return j


def _retopo(model: KinematicModel, kctx: KinContext) -> None:
    from stepscribe.understanding.kinematics import (
        _dof,
        _topology,
        axis_vector,
        refresh_description,
        rules,
    )

    ids = [g.id for g in model.links]
    model.dof, loops = _dof(model.joints, ids, {})
    up = axis_vector(kctx.asm.up_axis)
    model.topology = _topology(
        model.joints, model.links, kctx.by_id, up, kctx.asm, rules(), model.floating_groups, loops
    )  # type: ignore[assignment]
    refresh_description(model, kctx)
