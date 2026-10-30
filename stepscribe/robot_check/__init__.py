# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""``stepscribe validate-robot``: structural validity, simulator readiness and an optional library check.

Layer 1 (structural.py) and the readiness notes (readiness.py) need nothing but numpy. Layer 2
(backends.py) cross-checks forward kinematics with an optional library if one is installed. Validity
and readiness are reported separately: a correct file can still be one a simulator rejects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stepscribe.robot_check.backends import (
    INSTALL_HINT,
    FkBackend,
    available_backends,
    cross_check,
    default_backend,
)
from stepscribe.robot_check.findings import Finding, Layer2, ValidationReport
from stepscribe.robot_check.model import MAX_BYTES, UrdfError, parse_urdf, show
from stepscribe.robot_check.readiness import readiness_checks
from stepscribe.robot_check.structural import structural_checks
from stepscribe.text_safety import clean_name


def find_urdf(path: Path) -> Path:
    """The URDF a path stands for: the file itself, or robot.urdf in a pack or export folder."""
    if path.is_file():
        return path
    for candidate in (path / "robot.urdf", path / "pack" / "robot.urdf"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no robot.urdf in {path}")


def _read_robot_json(folder: Path, report: ValidationReport) -> dict[str, Any] | None:
    p = folder / "robot.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        report.structural.append(
            Finding(
                "S054",
                "warning",
                "robot.json next to the URDF could not be read, so the URDF was not compared with it.",
                "Write the pack again.",
            )
        )
        return None


def validate(
    path: str | Path,
    backend: str | None = None,
    n_random: int = 4,
    backends: dict[str, FkBackend] | None = None,
) -> ValidationReport:
    """Validate the URDF at *path* (a file, a pack or an export folder)."""
    urdf_path = find_urdf(Path(path))
    report = ValidationReport(source=clean_name(urdf_path.name))
    if urdf_path.stat().st_size > MAX_BYTES:
        report.structural.append(
            Finding(
                "S001",
                "error",
                "The file is larger than 20 MB, so it was not read.",
                "Check that it is a URDF.",
            )
        )
        return report
    text = urdf_path.read_text(encoding="utf-8", errors="replace")
    try:
        urdf = parse_urdf(text)
    except UrdfError as exc:
        report.structural.append(
            Finding(
                "S002",
                "error",
                f"The file cannot be read as a URDF: {clean_name(str(exc))}.",
                "Check that it is URDF text.",
            )
        )
        report.layer2 = Layer2("not_run", detail="skipped: the file could not be read")
        return report
    report.n_links, report.n_joints = len(urdf.links), len(urdf.joints)
    folder = urdf_path.parent
    robot = _read_robot_json(folder, report)
    report.structural += structural_checks(urdf, folder, robot)
    report.readiness = readiness_checks(urdf)
    if not report.structurally_valid:
        report.layer2 = Layer2("not_run", detail="skipped: fix the structural errors first")
        return report
    if backends is None:
        report.readiness += _simulator_readiness(urdf_path)
    found = backends if backends is not None else available_backends()
    chosen = found.get(backend) if backend else default_backend(found)
    if backend and chosen is None:
        report.layer2 = Layer2(
            "not_run", backend, f"the backend {show(backend)} is not installed. " + INSTALL_HINT
        )
    elif chosen is None:
        report.layer2 = Layer2("not_run", detail="no library is installed. " + INSTALL_HINT)
    else:
        report.layer2 = cross_check(urdf, urdf_path, chosen, n_random)
    return report


def _simulator_readiness(urdf_path: Path) -> list[Finding]:
    """MuJoCo's answer as readiness findings; none when MuJoCo is not installed."""
    try:
        from stepscribe.robot_check.adapters import mujoco_readiness

        return mujoco_readiness(urdf_path)
    except ImportError:
        return []


def format_report(report: ValidationReport) -> str:
    """The report as plain text: validity first, then readiness, then the library check."""
    lines = [
        f"Robot validation of {report.source}: {report.n_links} links, {report.n_joints} joints.",
        "",
    ]
    errors = [f for f in report.structural if f.severity == "error"]
    warns = [f for f in report.structural if f.severity != "error"]
    verdict = "VALID" if report.structurally_valid else "INVALID"
    lines.append(f"Structural validity: {verdict} ({len(errors)} errors, {len(warns)} warnings)")
    lines += _items(report.structural)
    lines.append("")
    issues = [f for f in report.readiness if f.severity in ("error", "warning")]
    ready = "READY" if report.simulator_ready else "NOT READY"
    lines.append(
        f"Simulator readiness: {ready} ({len(issues)} issues; this is separate from validity)"
    )
    lines += _items(report.readiness)
    lines.append("")
    l2 = report.layer2
    lines.append(
        f"Layer 2, cross-check with a robotics library: {l2.status.replace('_', ' ').upper()}"
    )
    if l2.detail:
        lines.append(f"  {l2.detail}")
    if l2.status in ("passed", "failed"):
        lines.append(
            f"  largest difference: position {l2.max_position_error_m:.3g} m, rotation {l2.max_rotation_error:.3g} rad"
        )
    lines += _items(l2.findings)
    return "\n".join(lines) + "\n"


def _items(findings: list[Finding]) -> list[str]:
    out = []
    for f in findings:
        out.append(f"  [{f.code}] {f.severity}: {f.message}")
        if f.fix:
            out.append(f"         Fix: {f.fix}")
    return out


__all__ = ["format_report", "validate", "find_urdf", "ValidationReport", "Finding"]
