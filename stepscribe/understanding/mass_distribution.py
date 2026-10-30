# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Mass distribution of parts, links and the whole assembly, and the text of its pack section.

Principal moments, principal axes and radii of gyration about the centre of mass, from geometry and
density. A value is given only for a valid closed solid with a known material or density; anything
else says ``not computed: <reason>``. The numbers are estimates and the text says so.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from stepscribe.describe.phrases import fmt
from stepscribe.models.schema import Instance, Part, Report
from stepscribe.understanding.process import complex_geometry_reason
from stepscribe.understanding.rigid_body import (
    STATIC_LABEL,
    Body,
    Payload,
    combine,
    principal_inertia,
)

ASSUMPTIONS = [
    "Estimates from CAD volume and the material or density named for each part; nothing is measured.",
    "Each part is taken as a solid of uniform density. Hollow, cast, welded or assembled-from-sheet parts, "
    "and models that are simplified outer skins, are not like that; the mass and inertia of such parts are wrong.",
    "A density guessed from a part name is a guess; the line says which parts rest on one.",
    "Moments are about the centre of mass, in the axes named; radii of gyration are k = sqrt(I / m).",
]


def _vec(v: Any) -> np.ndarray:
    return np.array([v.x, v.y, v.z], dtype=float)


def part_reason(part: Part) -> str | None:
    """Why the part's inertia is not computed, or None when it is."""
    if not part.is_valid_solid or part.topology.solids < 1:
        return "not a valid closed solid"
    if part.mass.mass_g is None or part.mass.inertia_tensor_g_mm2 is None:
        return "material or density unknown"
    return None


def part_body(part: Part) -> Body | str:
    """The part in its own frame: its mass, centroid and the inertia about it; or the reason."""
    reason = part_reason(part)
    if reason:
        return f"not computed: {reason}"
    assert part.mass.mass_g is not None and part.mass.inertia_tensor_g_mm2 is not None
    return Body(
        part.mass.mass_g, _vec(part.mass.centroid), np.array(part.mass.inertia_tensor_g_mm2, float)
    )


def _placed(part: Part, inst: Instance) -> Body | str:
    body = part_body(part)
    if isinstance(body, str):
        return body
    rot = np.array(inst.rotation_matrix, dtype=float)
    return Body(
        body.mass_g,
        rot @ body.com_mm + _vec(inst.position),
        rot @ body.inertia_g_mm2 @ rot.T,
    )


def reliable_body(part: Part, inst: Instance) -> Body | str:
    """As :func:`_placed`, but a part whose geometry is complex or free-form is refused too: its volume,
    and so its mass, is not that of a real solid. Used for loads, where a wrong mass changes the answer."""
    if complex_geometry_reason(part) is not None:
        return (
            "not computed: complex or free-form geometry (its volume is not that of a real solid)"
        )
    return _placed(part, inst)


def _combined(bodies: list[Body | str]) -> Body | str:
    reasons = sorted({b for b in bodies if isinstance(b, str)})
    if reasons or not bodies:
        return reasons[0] if reasons else "not computed: no parts"
    return combine([b for b in bodies if isinstance(b, Body)])


def link_body(report: Report, instance_ids: list[str], reliable: bool = False) -> Body | str:
    """Mass, centre and inertia of the instances of one link, in the file's axes; or a reason."""
    assert report.assembly is not None
    parts = {p.id: p for p in report.parts}
    by_id = {i.id: i for i in report.assembly.instances}
    make = reliable_body if reliable else _placed
    return _combined([make(parts[by_id[i].part_id], by_id[i]) for i in instance_ids])


def assembly_body(report: Report) -> Body | str:
    assert report.assembly is not None
    ids = [i.id for i in report.assembly.instances]
    return link_body(report, ids)


def principal_dict(body: Body | str) -> dict[str, Any]:
    """Moments (ascending), axes (rows) and radii of gyration of a body, or the refusal."""
    if isinstance(body, str):
        return {"status": "not computed", "reason": body.removeprefix("not computed: ")}
    p = principal_inertia(body.inertia_g_mm2, body.mass_g)
    return {
        "status": "computed",
        "mass_g": body.mass_g,
        "com_mm": body.com_mm.tolist(),
        "moments_g_mm2": p.moments_g_mm2.tolist(),
        "axes": p.axes.tolist(),
        "radii_of_gyration_mm": p.radii_mm.tolist(),
    }


def payload_from_context(ctx: dict[str, Any]) -> tuple[Payload | None, str | None]:
    """The designer's ``payload:`` as ``(payload, None)``, ``(None, None)`` when absent, or
    ``(None, why it was ignored)``. ``mass_kg`` > 0; ``offset_mm`` three numbers (file axes) from the
    last joint's axis point, default zero."""
    raw = ctx.get("payload")
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        return None, "payload ignored: it must be a mapping with mass_kg and offset_mm"
    try:
        mass = float(raw["mass_kg"])
        offset = [float(v) for v in raw.get("offset_mm", [0, 0, 0])]
    except (KeyError, TypeError, ValueError):
        return None, "payload ignored: mass_kg must be a number and offset_mm three numbers"
    if (
        len(offset) != 3
        or not math.isfinite(mass)
        or mass <= 0
        or not all(map(math.isfinite, offset))
    ):
        return None, "payload ignored: mass_kg must be above 0 and offset_mm three finite numbers"
    return Payload(mass, np.array(offset)), None


def mass_distribution(report: Report) -> dict[str, Any]:
    """Principal inertia of every part, of every link (robots) and of the assembly (>= 2 bodies)."""
    parts = [
        {
            "id": p.id,
            "material_source": p.mass.material_source,
            **principal_dict(part_body(p)),
        }
        for p in report.parts
    ]
    out: dict[str, Any] = {
        "label": "estimate from geometry and density; not measured",
        "assumptions": ASSUMPTIONS,
        "units": {"length": "mm", "mass": "g", "inertia": "g*mm^2"},
        "parts": parts,
    }
    asm = report.assembly
    if asm is not None:
        out["assembly"] = principal_dict(assembly_body(report))
        if report.understanding is not None:
            out["links"] = [
                {"id": g.id, **principal_dict(link_body(report, g.instance_ids))}
                for g in report.understanding.kinematics.links
            ]
    guessed = sorted(p.id for p in report.parts if p.mass.material_source == "name_guess")
    if guessed:
        out["density_guessed_from_name"] = guessed
    return out


def _vec_text(v: list[float], nd: int = 3) -> str:
    return "(" + ", ".join(fmt(x, nd) for x in v) + ")"


def _principal_lines(label: str, d: dict[str, Any]) -> list[str]:
    if d["status"] != "computed":
        return [f"- {label}: not computed: {d['reason']}"]
    mom = d["moments_g_mm2"]
    k = d["radii_of_gyration_mm"]
    lines = [
        f"- {label}: mass {fmt(d['mass_g'])} g, centre of mass {_vec_text(d['com_mm'], 1)} mm; "
        f"principal moments {', '.join(fmt(m, 1) for m in mom)} g*mm^2; "
        f"radii of gyration {', '.join(fmt(x, 2) for x in k)} mm"
    ]
    for m, ax in zip(mom, d["axes"], strict=True):
        lines.append(f"  - moment {fmt(m, 1)} about axis {_vec_text(ax)}")
    return lines


def mass_markdown(
    dist: dict[str, Any], robot: dict[str, Any] | None, payload_note: str | None = None
) -> str:
    """The pack section: principal inertia of the assembly, links and parts, and static joint loads."""
    lines = ["## Mass distribution and static load (estimates)", ""]
    lines += [f"- {a}" for a in ASSUMPTIONS]
    lines.append("")
    if "assembly" in dist:
        lines += _principal_lines("Assembly", dist["assembly"])
    for link in dist.get("links", []):
        lines += _principal_lines(f"Link {link['id']}", link)
    for part in dist["parts"]:
        lines += _principal_lines(f"Part {part['id']}", part)
    if dist.get("density_guessed_from_name"):
        lines.append(
            "- Density assumed from the part name (a guess) for: "
            + ", ".join(dist["density_guessed_from_name"])
        )
    loads = (robot or {}).get("static_holding_loads")
    if loads:
        lines += ["", f"### Joint loads: {STATIC_LABEL}", ""]
        if loads["payload"]:
            p = loads["payload"]
            lines.append(
                f"- Payload (given by the designer): {fmt(p['mass_kg'])} kg at {_vec_text(p['offset_mm'], 1)} mm "
                "from the last joint's axis point, in the file's axes."
            )
        elif payload_note:
            lines.append(f"- {payload_note}")
        else:
            lines.append("- No payload given: the arm's own weight only.")
        for j in loads["joints"]:
            if j["value"] is None:
                lines.append(f"- {j['joint']} ({j['type']}): {j['reason']}")
            else:
                lines.append(
                    f"- {j['joint']} ({j['type']}): holding {fmt(j['value'], 3)} {j['unit']} "
                    f"(magnitude {fmt(abs(j['value']), 3)} {j['unit']}); the sign is the direction "
                    "about the joint's positive axis"
                )
    elif payload_note:
        lines += ["", f"- {payload_note}"]
    return "\n".join(lines) + "\n"
