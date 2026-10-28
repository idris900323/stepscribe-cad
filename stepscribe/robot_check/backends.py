# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Layer 2: the plug-in structure for an optional robotics library, and the cross-check itself.

No library is a dependency of stepscribe. ``pip install 'stepscribe[robot]'`` adds the two adapters
in :mod:`stepscribe.robot_check.adapters` (yourdfpy, MuJoCo). A backend is any object with the shape of
:class:`FkBackend`, registered here (``register_backend``) or published by another package under the
entry-point group ``stepscribe.robot_fk``. With none installed, layer 1 still runs and the report says
so. The cross-check compares the link transforms the library computes with stepscribe's own
(:mod:`stepscribe.robot_check.fk`) at the zero pose and at fixed pseudo-random poses.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

from stepscribe.robot_check.findings import Finding, Layer2
from stepscribe.robot_check.fk import link_transforms, pose_values, rotation_error
from stepscribe.robot_check.model import Urdf, show
from stepscribe.text_safety import clean_name

ENTRY_POINT_GROUP = "stepscribe.robot_fk"
POSITION_TOL_M = 1e-6
ROTATION_TOL_RAD = 1e-6
DEFAULT_BACKEND = "yourdfpy"  # the independent kinematics implementation; used when none is named
INSTALL_HINT = (
    "Layer 2 needs an optional robotics library: pip install 'stepscribe[robot]' "
    "(yourdfpy for the kinematics cross-check, MuJoCo for simulator readiness). A library "
    f"packaged as a stepscribe plug-in (entry-point group {ENTRY_POINT_GROUP}) is found automatically."
)


class FkBackend(Protocol):
    """What a library adapter provides."""

    name: str

    def version(self) -> str: ...

    def load(self, urdf_path: Path) -> None:
        """Read the URDF (raise on anything the library rejects)."""

    def link_transforms(self, values: dict[str, float]) -> dict[str, np.ndarray]:
        """4x4 world transform of every link at the given joint values (by joint name)."""


Factory = Callable[[], FkBackend]
_REGISTRY: dict[str, Factory] = {}


def register_backend(name: str, factory: Factory) -> None:
    """Make a backend available; the factory raises ImportError when its library is missing."""
    _REGISTRY[name] = factory


def unregister_backend(name: str) -> None:
    _REGISTRY.pop(name, None)


def _builtin() -> None:
    from stepscribe.robot_check.adapters import MujocoBackend, YourdfpyBackend

    for factory in (YourdfpyBackend, MujocoBackend):
        _REGISTRY.setdefault(factory.name, factory)


def _discover() -> None:
    _builtin()
    for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        if ep.name not in _REGISTRY:
            try:
                register_backend(ep.name, ep.load())
            except Exception:  # noqa: BLE001 - a broken plug-in must not stop the validation
                continue


def available_backends() -> dict[str, FkBackend]:
    """Name -> a ready backend instance, for every registered backend whose library imports."""
    _discover()
    out: dict[str, FkBackend] = {}
    for name in sorted(_REGISTRY):
        try:
            out[name] = _REGISTRY[name]()
        except Exception:  # noqa: BLE001 - not installed, or broken: not available
            continue
    return out


def default_backend(found: dict[str, FkBackend]) -> FkBackend | None:
    """The backend used when none is named: yourdfpy if installed, else the first available."""
    if DEFAULT_BACKEND in found:
        return found[DEFAULT_BACKEND]
    return next(iter(found.values())) if found else None


def cross_check(
    urdf: Urdf, path: Path, backend: FkBackend, n_random: int = 4, seed: int = 20260101
) -> Layer2:
    """Compare the backend's link transforms with the numpy ones at the zero pose and *n_random* poses."""
    name = clean_name(getattr(backend, "name", "")) or "backend"
    try:
        backend.load(path)
        version = clean_name(backend.version())
    except Exception as exc:  # noqa: BLE001 - what the library says about the file is a finding
        why = clean_name(f"{type(exc).__name__}: {exc}")[:300]
        return Layer2(
            "failed",
            name,
            f"{name} could not load the file",
            findings=[
                Finding(
                    "X001",
                    "error",
                    f"{name} rejected the URDF: {why}",
                    "Fix what the library names, then validate again.",
                )
            ],
        )
    poses = pose_values(urdf, n_random, seed)
    max_pos = max_rot = 0.0
    findings: list[Finding] = []
    for i, values in enumerate(poses):
        mine = link_transforms(urdf, values)
        try:
            theirs = backend.link_transforms(values)
        except Exception as exc:  # noqa: BLE001
            why = clean_name(f"{type(exc).__name__}: {exc}")[:300]
            return Layer2(
                "error", name, f"{name} could not compute the pose: {why}", i, max_pos, max_rot
            )
        for link, t in sorted(mine.items()):
            if link not in theirs:
                findings.append(
                    Finding(
                        "X002",
                        "error",
                        f"{name} has no transform for link {show(link)}.",
                        "Check that the library loaded the whole tree.",
                        show(link),
                    )
                )
                continue
            dp = float(np.linalg.norm(t[:3, 3] - theirs[link][:3, 3]))
            dr = rotation_error(t, theirs[link])
            max_pos, max_rot = max(max_pos, dp), max(max_rot, dr)
            if dp > POSITION_TOL_M or dr > ROTATION_TOL_RAD:
                label = "the zero pose" if i == 0 else f"pose {i}"
                findings.append(
                    Finding(
                        "X003",
                        "error",
                        f"Link {show(link)} differs at {label}: position {dp:.3g} m, rotation {dr:.3g} rad "
                        f"between stepscribe and {name}.",
                        "A joint origin, axis or rpy is read differently; check that joint and its parent chain.",
                        show(link),
                    )
                )
    status: Literal["passed", "failed"] = "failed" if findings else "passed"
    detail = f"{name} {version}: {len(poses)} poses (zero and {len(poses) - 1} fixed random)"
    return Layer2(status, name, detail, len(poses), max_pos, max_rot, findings[:20])
