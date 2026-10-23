"""Build the project inside the tests without touching the network.

``python -m build`` normally creates an isolated environment and downloads the build backend from
PyPI; a network hiccup there made four unit tests fail once. The unit tests therefore build with
``--no-isolation`` against the pinned ``hatchling`` of the dev environment. One isolated build
still runs, as the ``isolated-build`` job in .github/workflows/ci.yml (and at release time).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_build(*args: str, cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    """``python -m build --no-isolation *args``; fails with the full output when it does not work."""
    try:
        import hatchling  # noqa: F401 - the pinned dev dependency that does the build
    except ImportError as exc:
        raise AssertionError(
            "hatchling is not installed: it is a pinned dev dependency (pip install -e .[dev])"
        ) from exc
    res = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert res.returncode == 0, (
        "python -m build failed:\n" + res.stdout[-2500:] + res.stderr[-2500:]
    )
    return res
