"""The CI guard that keeps the POSIX-only tests from being skipped on Linux and macOS."""

from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET  # noqa: S405 - pytest's own output
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


@pytest.mark.parametrize("reason", ["needs Windows PowerShell", "Windows console API"])
def test_windows_only_tests_may_be_skipped_everywhere_else(tmp_path: Path, reason: str) -> None:
    mod = _load()
    xml = _junit(tmp_path, reason)
    assert mod.unexpected_skips(xml, "linux") == []
    assert mod.unexpected_skips(xml, "darwin") == []
    assert mod.unexpected_skips(xml, "win32"), "on Windows these must run"


def test_a_missing_report_says_pytest_did_not_finish(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    mod = _load()
    assert mod.main(["check_skips.py", str(tmp_path / "junit.xml")]) == 1
    assert "did not run to the end" in capsys.readouterr().out


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


def test_ci_and_release_run_the_whole_suite_not_the_fast_subset() -> None:
    """`-m "not slow"` is for local runs only: nothing may deselect tests by default or in CI."""
    root = Path(__file__).parent.parent
    for flow in ("ci.yml", "release.yml"):
        text = (root / ".github" / "workflows" / flow).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "pytest" in line:
                assert "-m " not in line and "slow" not in line, f"{flow}: {line.strip()}"
    options = (
        (root / "pyproject.toml").read_text(encoding="utf-8").split("[tool.pytest.ini_options]")[1]
    )
    options = options.split("\n[", 1)[0]
    addopts = [line for line in options.splitlines() if line.startswith("addopts")]
    assert addopts == ['addopts = "-q"'], addopts


def test_deselected_tests_are_not_counted_as_skips(tmp_path: Path) -> None:
    """A deselected test is absent from the junit file, so it is neither a skip nor a failure."""
    import subprocess
    import sys

    mod = _load()
    (tmp_path / "test_two.py").write_text(
        "import pytest\n\n@pytest.mark.slow\ndef test_slow(): pass\n\ndef test_fast(): pass\n",
        encoding="utf-8",
    )
    junit = tmp_path / "junit.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-m", "not slow",
         f"--junitxml={junit}", "-o", "markers=slow: x", str(tmp_path / "test_two.py")],
        check=True, capture_output=True, cwd=tmp_path,
    )  # fmt: skip
    names = [
        c.get("name")
        for c in ET.parse(junit).iter("testcase")  # noqa: S314 - pytest's own output
    ]
    assert names == ["test_fast"]
    assert mod.unexpected_skips(str(junit), "linux") == []
    assert mod.main(["check_skips.py", str(junit)]) == 0


def test_the_macos_only_memory_test_may_not_be_skipped_on_macos(tmp_path: Path) -> None:
    mod = _load()
    xml = _junit(tmp_path, "only on macOS: it reads the real vm_stat")
    assert mod.unexpected_skips(xml, "linux") == []
    assert mod.unexpected_skips(xml, "win32") == []
    assert len(mod.unexpected_skips(xml, "darwin")) == 1  # on macOS it must run
