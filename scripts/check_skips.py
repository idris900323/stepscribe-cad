# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Fail CI if a test was skipped for a reason that is not expected on this OS.

    pytest --junitxml=junit.xml && python scripts/check_skips.py junit.xml

The POSIX-only tests (private cache permissions, symlink refusal, process groups) may be skipped
on Windows only; the Windows-only tests (real shortcut, console handler) everywhere else. A skip
anywhere they must run means the check silently stopped running.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path  # noqa: S405 - our own pytest output

EVERYWHERE = ("the claude CLI is not installed",)
WINDOWS_ONLY = ("POSIX permissions", "needs symlinks", "POSIX process groups")
NO_GL = ("off-screen rendering is not available on this machine",)  # bare macOS / Windows VMs
NOT_MACOS = ("only on macOS: it reads the real vm_stat",)  # the one test of the macOS memory query
NOT_WINDOWS = ("needs Windows PowerShell", "Windows console API")  # the Windows-only tests

ALLOWED: dict[str, tuple[str, ...]] = {
    "linux": EVERYWHERE
    + NOT_WINDOWS
    + NOT_MACOS,  # xvfb provides OpenGL, so rendering tests must run
    "darwin": EVERYWHERE + NOT_WINDOWS + NO_GL,
    "win32": EVERYWHERE + WINDOWS_ONLY + NO_GL + NOT_MACOS,
}


def unexpected_skips(junit_xml: str, platform: str) -> list[str]:
    """``test id: reason`` for every skipped test whose reason is not allowed on *platform*."""
    allowed = ALLOWED.get(platform, EVERYWHERE)
    bad: list[str] = []
    for case in ET.parse(junit_xml).iter("testcase"):  # noqa: S314
        for skipped in case.findall("skipped"):
            reason = skipped.get("message", "")
            if not any(a in reason for a in allowed):
                bad.append(f"{case.get('classname')}::{case.get('name')}: {reason}")
    return bad


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else "junit.xml"
    if not Path(path).is_file():
        print(f"{path} was not written: pytest did not run to the end, see the failure above.")
        return 1
    bad = unexpected_skips(path, sys.platform)
    for line in bad:
        print("unexpected skip:", line)
    if bad:
        print(f"{len(bad)} test(s) were skipped that must run on {sys.platform}.")
        return 1
    print(f"All skips are expected on {sys.platform}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
