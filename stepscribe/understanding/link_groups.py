# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Link groups from part names: BASE, LINK<n>, AXIS<n>, with any prefix and a _body<k> suffix.

Robot files from vendors name their solids ``<model>_<rev>_LINK3_body2``. When at least three
distinct numbered groups exist and they touch in order, the names are a stronger signal than
contact geometry, so same-group bodies are one link and different groups are never merged just
because they rest on each other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stepscribe import config
from stepscribe.features.hole_standards import load_table

if TYPE_CHECKING:
    from stepscribe.assembly.tree import InstanceData
    from stepscribe.models.schema import AssemblyInfo

# letters on either side would make "sublink2" or "baseplate" a match; digits and "_" do not
_LINK = re.compile(r"(?<![A-Za-z])(?:link|axis)[ _-]?(\d+)(?!\d)", re.IGNORECASE)
_BASE = re.compile(r"(?<![A-Za-z])base(?![A-Za-z])", re.IGNORECASE)


@dataclass
class NameGroups:
    """Link group of each instance (by name), the group order and how sure we are."""

    group_of: dict[str, str]  # instance id -> "BASE" / "LINK3"
    number: dict[str, int]  # group -> its number (BASE is 0)
    confidence: float

    def same(self, a: str, b: str) -> bool:
        ga, gb = self.group_of.get(a), self.group_of.get(b)
        return ga is not None and ga == gb

    def differ(self, a: str, b: str) -> bool:
        ga, gb = self.group_of.get(a), self.group_of.get(b)
        return ga is not None and gb is not None and ga != gb


def parse_group(*names: str) -> tuple[str, int] | None:
    """('LINK3', 3) / ('BASE', 0) for the first name that has a pattern, else None."""
    for name in names:
        m = _LINK.search(name)
        if m:
            n = int(m.group(1))
            return f"LINK{n}", n
    for name in names:
        if _BASE.search(name):
            return "BASE", 0
    return None


def _adjacent_groups(asm: AssemblyInfo, group_of: dict[str, str]) -> set[frozenset[str]]:
    """Pairs of groups that touch (or are held together by a hole stack)."""
    pairs: set[frozenset[str]] = set()
    for c in asm.contacts:
        if c.kind == "near_miss":
            continue
        if c.kind != "cylindrical_fit" and c.min_distance_mm >= config.CONTACT_TOL:
            continue
        ga, gb = group_of.get(c.instance_a), group_of.get(c.instance_b)
        if ga and gb and ga != gb:
            pairs.add(frozenset((ga, gb)))
    for j in asm.fastener_joints:
        groups = [group_of.get(i) for i in j.instance_ids]
        for x in range(len(groups)):
            for y in range(x + 1, len(groups)):
                if groups[x] and groups[y] and groups[x] != groups[y]:
                    pairs.add(frozenset((groups[x], groups[y])))  # type: ignore[arg-type]
    return pairs


def detect_name_groups(insts: list[InstanceData], asm: AssemblyInfo) -> NameGroups | None:
    """The name groups when at least three numbered ones form a chain in the contact graph."""
    cfg = load_table("roles.yaml")["kinematics"]["name_groups"]
    group_of: dict[str, str] = {}
    number: dict[str, int] = {}
    for inst in insts:
        found = parse_group(inst.name, inst.ap.part.name)
        if found is not None:
            group_of[inst.id] = found[0]
            number[found[0]] = found[1]
    numbered = sorted(n for g, n in number.items() if g != "BASE")
    if len(numbered) < int(cfg["min_numbered_groups"]):
        return None
    adjacent = _adjacent_groups(asm, group_of)
    by_number = {n: g for g, n in number.items()}
    for lo, hi in zip(numbered, numbered[1:], strict=False):
        if frozenset((by_number[lo], by_number[hi])) not in adjacent:
            return None
    return NameGroups(group_of, number, float(cfg["confidence"]))
