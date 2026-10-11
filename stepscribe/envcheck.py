# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Is the OpenCASCADE wheel the one stepscribe was written for? One clear line if not."""

from __future__ import annotations

REQUIRED_MAJOR = 8
FIX = 'python -m pip install -U "cadquery-ocp>=8,<9"'


class EnvironmentProblem(RuntimeError):
    """The environment cannot run the analysis; the message is one line with the fix."""


def installed_occt() -> str | None:
    """OCCT version of the installed OCP wheel (``OCP.__version__`` tracks OCCT), or None."""
    try:
        import OCP
    except ImportError:
        return None
    return str(OCP.__version__)


def check_occt(version: str | None = None) -> None:
    """Raise :class:`EnvironmentProblem` unless OCCT 8 is installed."""
    found = version if version is not None else installed_occt()
    if found is None:
        raise EnvironmentProblem(
            'stepscribe needs OpenCASCADE; run: python -m pip install "cadquery-ocp>=8,<9"'
        )
    try:
        major = int(found.split(".")[0])
    except ValueError:
        major = -1
    if major != REQUIRED_MAJOR:
        raise EnvironmentProblem(f"stepscribe needs OCCT {REQUIRED_MAJOR}; run: {FIX}")
