# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""What the validation reports: a finding, and the two verdicts that are kept apart."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["error", "warning", "info"]


@dataclass
class Finding:
    code: str  # S### structural, R### readiness, X### cross-check
    severity: Severity
    message: str  # plain words
    fix: str = ""  # what to change
    where: str = ""  # a link or joint name, already cleaned


@dataclass
class Layer2:
    """The optional-library cross-check: not run, run and passed, or run and found differences."""

    status: Literal["not_run", "passed", "failed", "error"]
    backend: str | None = None
    detail: str = ""
    poses: int = 0
    max_position_error_m: float = 0.0
    max_rotation_error: float = 0.0
    findings: list[Finding] = field(default_factory=list)


@dataclass
class ValidationReport:
    source: str
    structural: list[Finding] = field(default_factory=list)
    readiness: list[Finding] = field(default_factory=list)
    layer2: Layer2 = field(default_factory=lambda: Layer2("not_run"))
    n_links: int = 0
    n_joints: int = 0

    @property
    def structurally_valid(self) -> bool:
        return not any(f.severity == "error" for f in self.structural)

    @property
    def simulator_ready(self) -> bool:
        return not any(f.severity in ("error", "warning") for f in self.readiness)
