# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Optional learned role models: one more evidence source, never a replacement for the rules.

A role model is a Python package that registers a callable in the entry-point group
``stepscribe.role_models``. The callable takes a :class:`~stepscribe.models.schema.Part` and
returns ``{role: probability}`` with roles from ``roles.yaml``.

A model is third-party code, so it is never imported on its own: it runs only when the user names
it, with ``STEPSCRIBE_ML=name1,name2`` or ``ml: {enabled: [name1]}`` in ``design_context.yaml``.
The models that ran are listed (name, package, version) in the report and in the pack. See
``docs/future_ml.md`` for the bar a model has to clear before it is worth using.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from stepscribe.models.schema import Part

RoleModel = Callable[[Part], dict[str, float]]
GROUP = "stepscribe.role_models"


@dataclass
class Loaded:
    """The models that were switched on: callables, who provides them, and what went wrong."""

    models: dict[str, RoleModel] = field(default_factory=dict)
    info: list[dict[str, str]] = field(default_factory=list)  # name, distribution, version
    problems: list[str] = field(default_factory=list)  # asked for but not installed or broken


def enabled_names(
    context: Mapping[str, Any] | None = None, env: Mapping[str, str] | None = None
) -> list[str]:
    """Model names the user switched on: ``STEPSCRIBE_ML`` plus ``ml.enabled`` in the context."""
    e = os.environ if env is None else env
    names = [n.strip() for n in e.get("STEPSCRIBE_ML", "").split(",") if n.strip()]
    ml = (context or {}).get("ml")
    enabled = ml.get("enabled") if isinstance(ml, dict) else None
    if isinstance(enabled, (list, tuple)):
        names += [str(n).strip() for n in enabled if str(n).strip()]
    return sorted(dict.fromkeys(names))


def load_enabled(
    context: Mapping[str, Any] | None = None, env: Mapping[str, str] | None = None
) -> Loaded:
    """Import only the models the user named. Nothing is imported when none is named."""
    names = enabled_names(context, env)
    out = Loaded()
    if not names:
        return out
    available = {ep.name: ep for ep in entry_points(group=GROUP)}
    for name in names:
        ep = available.get(name)
        if ep is None:
            out.problems.append(name)
            continue
        try:
            out.models[name] = ep.load()
        except Exception:  # noqa: BLE001 - a broken optional plugin must not break the analysis
            out.problems.append(name)
            continue
        dist = getattr(ep, "dist", None)
        out.info.append(
            {
                "name": name,
                "distribution": str(getattr(dist, "name", "unknown")),
                "version": str(getattr(dist, "version", "unknown")),
            }
        )
    return out


def load_role_models(context: Mapping[str, Any] | None = None) -> dict[str, RoleModel]:
    """The role models the user switched on (none by default)."""
    return load_enabled(context).models


def role_scores(
    part: Part, models: dict[str, RoleModel], weight: float
) -> dict[str, tuple[str, float]]:
    """Role -> (model name, evidence weight) from every model; a probability times *weight*."""
    best: dict[str, tuple[str, float]] = {}
    for name, model in sorted(models.items()):
        try:
            probs = model(part)
        except Exception:  # noqa: BLE001
            continue
        for role, p in probs.items():
            w = float(p) * weight
            if w > 0 and (role not in best or w > best[role][1]):
                best[role] = (name, w)
    return best
