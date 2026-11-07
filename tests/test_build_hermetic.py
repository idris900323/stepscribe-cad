"""The unit tests never download a build backend; one CI job builds in an isolated environment."""

from __future__ import annotations

import re
import tomllib
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_hatchling_is_pinned_in_the_dev_dependencies_and_matches_the_environment() -> None:
    dev = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]["dev"]
    pins = [d for d in dev if d.startswith("hatchling")]
    assert pins == [f"hatchling=={version('hatchling')}"], pins


def test_unit_tests_build_only_through_the_hermetic_helper() -> None:
    offenders = []
    for path in (ROOT / "tests").glob("*.py"):
        if path.name in ("build_helper.py", "test_build_hermetic.py"):
            continue
        if re.search(r'"-m",\s*"build"', path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert not offenders, f"these call python -m build directly (network needed): {offenders}"


def test_one_ci_job_still_builds_in_an_isolated_environment() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "isolated-build:" in ci
    job = ci.split("isolated-build:", 1)[1]
    assert "python -m build" in job and "--no-isolation" not in job
