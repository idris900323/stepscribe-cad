# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""``stepscribe doctor``: what is installed, what works, and the fix for each problem.

Light on purpose: nothing here imports OpenCASCADE or VTK at module level, so the report can be
produced even when those are broken. Every fact comes from a probe, so tests can fake any machine.
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

Level = Literal["ok", "warn", "fail"]
MIN_PYTHON = (3, 11)
LOW_RAM_BYTES = 2 * 1024**3
OCCT_FIX = 'python -m pip install -U "cadquery-ocp>=8,<9"'


@dataclass
class Check:
    name: str
    level: Level
    detail: str
    fix: str = ""


@dataclass
class Probe:
    """Where the facts come from (replaced by fakes in tests)."""

    python: Callable[[], tuple[int, int, int]]
    stepscribe: Callable[[], str]
    occt: Callable[[], str | None]
    vtk: Callable[[], str | None]
    mcp: Callable[[], str | None]
    rendering: Callable[[], bool]
    cache: Callable[[], dict[str, Any]]
    free_ram: Callable[[], int | None]
    cpus: Callable[[], int]


def _dist_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def rendering_ok() -> bool:
    """True when VTK can draw off-screen here (checked in a child process: a bad driver crashes)."""
    try:
        done = subprocess.run(
            [sys.executable, "-c", "from stepscribe.render.raster import _smoke; _smoke()"],
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def rendering_message() -> str | None:
    """A sentence for the web page when images cannot be drawn, else None."""
    if rendering_ok():
        return None
    return (
        "Images cannot be drawn on this computer (no usable OpenGL), so packs are written "
        "without images. Run: python -m stepscribe doctor"
    )


def default_probe() -> Probe:
    from stepscribe import __version__, cache, envcheck

    def free_ram() -> int | None:
        from stepscribe.analysis import available_ram_bytes

        return available_ram_bytes()

    return Probe(
        python=lambda: (sys.version_info[0], sys.version_info[1], sys.version_info[2]),
        stepscribe=lambda: __version__,
        occt=envcheck.installed_occt,
        vtk=lambda: _dist_version("vtk"),
        mcp=lambda: _dist_version("mcp"),
        rendering=rendering_ok,
        cache=cache.info,
        free_ram=free_ram,
        cpus=lambda: os.cpu_count() or 1,
    )


def _occt_check(version: str | None) -> Check:
    name = "OpenCASCADE"
    if version is None:
        return Check(
            name,
            "fail",
            "not installed",
            'python -m pip install "cadquery-ocp>=8,<9"',
        )
    try:
        major = int(version.split(".")[0])
    except ValueError:
        major = -1
    if major < 8:
        return Check(name, "fail", f"OCCT {version} (stepscribe needs OCCT 8)", OCCT_FIX)
    if major > 8:
        return Check(
            name,
            "warn",
            f"OCCT {version} (stepscribe is tested with OCCT 8)",
            'python -m pip install -U "cadquery-ocp>=8,<9"',
        )
    return Check(name, "ok", f"OCCT {version}")


def run_checks(probe: Probe | None = None) -> list[Check]:
    """Every check, in the order they are shown."""
    p = probe or default_probe()
    out: list[Check] = []

    py = p.python()
    py_text = ".".join(str(n) for n in py)
    if py[:2] >= MIN_PYTHON:
        out.append(Check("Python", "ok", py_text))
    else:
        out.append(
            Check(
                "Python",
                "fail",
                f"{py_text} (stepscribe needs 3.11 or newer)",
                "Install Python 3.11 or newer from python.org, then reinstall stepscribe-cad.",
            )
        )
    out.append(Check("stepscribe", "ok", p.stepscribe()))
    out.append(_occt_check(p.occt()))

    vtk = p.vtk()
    out.append(
        Check("VTK", "ok", vtk)
        if vtk
        else Check("VTK", "fail", "not installed", "python -m pip install vtk")
    )
    mcp = p.mcp()
    out.append(
        Check("MCP", "ok", mcp)
        if mcp
        else Check(
            "MCP",
            "warn",
            "not installed (optional: only the Claude Code plugin and MCP clients need it)",
            'python -m pip install "stepscribe-cad[mcp]"',
        )
    )

    out.append(
        Check("Rendering", "ok", "off-screen drawing works")
        if p.rendering()
        else Check(
            "Rendering",
            "warn",
            "off-screen drawing does not work here; packs are written without images",
            "Linux: apt install xvfb libgl1-mesa-dri and run under xvfb-run -a; "
            "Windows/macOS: update the graphics driver; or pass --no-images",
        )
    )

    info = p.cache()
    where = f"{info['path']} ({info['entries']} entries, {info['bytes'] / 1024**2:.1f} MB)"
    if info.get("fallback_reason"):
        out.append(
            Check(
                "Cache",
                "warn",
                f"{where}; the usual folder was not used because it {info['fallback_reason']}",
                "Set STEPSCRIBE_CACHE to a folder only you can write to.",
            )
        )
    else:
        out.append(Check("Cache", "ok", where))

    ram = p.free_ram()
    if ram is None:
        out.append(Check("Memory", "ok", "free memory is not reported by this OS"))
    elif ram < LOW_RAM_BYTES:
        out.append(
            Check(
                "Memory",
                "warn",
                f"{ram / 1024**3:.1f} GB free",
                "Close other programs. A big file needs about 0.4 GB per worker; "
                "set STEPSCRIBE_WORKERS=1 to use less.",
            )
        )
    else:
        out.append(Check("Memory", "ok", f"{ram / 1024**3:.1f} GB free"))

    cpus = p.cpus()
    if cpus <= 1:
        out.append(
            Check(
                "CPUs",
                "warn",
                "1: analysis will run on one process",
                "Fine for small files; big assemblies will take longer.",
            )
        )
    else:
        out.append(Check("CPUs", "ok", str(cpus)))
    return out


def format_report(checks: list[Check]) -> str:
    lines: list[str] = []
    for c in checks:
        lines.append(f"[{c.level}] {c.name} {c.detail}")
        if c.level != "ok" and c.fix:
            lines.append(f"      fix: {c.fix}")
    return "\n".join(lines)
