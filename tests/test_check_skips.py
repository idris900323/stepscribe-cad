"""The CI guard that keeps the POSIX-only tests from being skipped on Linux and macOS."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_skips.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_skips", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _junit(tmp_path: Path, *reasons: str) -> str:
    cases = "".join(
        f'<testcase classname="t.mod" name="test_{i}"><skipped type="pytest.skip" '
        f'message="{reason}"/></testcase>'
        for i, reason in enumerate(reasons)
    )
    path = tmp_path / "junit.xml"
    path.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>", encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("reason", ["POSIX permissions", "needs symlinks", "POSIX process groups"])
def test_posix_tests_may_only_be_skipped_on_windows(tmp_path: Path, reason: str) -> None:
    mod = _load()
    xml = _junit(tmp_path, reason)
    assert mod.unexpected_skips(xml, "win32") == []
    assert len(mod.unexpected_skips(xml, "linux")) == 1
    assert len(mod.unexpected_skips(xml, "darwin")) == 1


def test_a_missing_optional_dependency_is_never_an_allowed_skip(tmp_path: Path) -> None:
    mod = _load()
    xml = _junit(tmp_path, "could not import 'psutil': No module named 'psutil'")
    for platform in ("linux", "darwin", "win32"):
        assert mod.unexpected_skips(xml, platform), platform


def test_rendering_may_not_be_skipped_on_linux(tmp_path: Path) -> None:
    mod = _load()
    xml = _junit(tmp_path, "off-screen rendering is not available on this machine")
    assert mod.unexpected_skips(xml, "linux")
    assert mod.unexpected_skips(xml, "darwin") == []


def test_ci_runs_the_guard_and_provides_node_and_psutil() -> None:
    root = Path(__file__).parent.parent
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--junitxml=junit.xml" in ci and "scripts/check_skips.py junit.xml" in ci
    assert "actions/setup-node" in ci
    assert "psutil" in (root / "pyproject.toml").read_text(encoding="utf-8")
