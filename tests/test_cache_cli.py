"""H3: cache commands, resource options and the large-file warning on the command line."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stepscribe import cache, limits
from stepscribe.cli import app

runner = CliRunner()


def _entry(root: Path, name: str, size: int, age_s: float) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "blob.bin").write_bytes(b"x" * size)
    t = time.time() - age_s
    os.utime(d / "blob.bin", (t, t))
    os.utime(d, (t, t))
    return d


def test_cache_info_and_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "c"))
    root = cache.cache_root()
    _entry(root, "a", 1000, 5)
    _entry(root, "b", 2000, 5)
    info = runner.invoke(app, ["cache", "info"])
    assert info.exit_code == 0, info.output
    assert str(root) in info.output and "2 entries" in info.output and "limit" in info.output
    cleared = runner.invoke(app, ["cache", "clear"])
    assert cleared.exit_code == 0 and "Removed 2" in cleared.output
    assert cache.info()["entries"] == 0


def test_cache_max_gb_option_sets_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STEPSCRIBE_CACHE_MAX_GB", raising=False)
    assert cache.max_bytes() == 2 * 1024**3, "default: 2 GB"
    cache.set_max_gb(0.5)
    assert cache.max_bytes() == 512 * 1024**2
    monkeypatch.delenv("STEPSCRIBE_CACHE_MAX_GB", raising=False)


def test_ui_and_mcp_list_the_resource_options() -> None:
    ui = runner.invoke(app, ["ui", "--help"]).output
    for flag in ("--max-jobs", "--session-idle-min", "--cache-max-gb", "--max-upload-mb"):
        assert flag in ui, flag
    mcp = runner.invoke(app, ["mcp", "--help"]).output
    assert "--max-jobs" in mcp and "--cache-max-gb" in mcp


def test_export_warns_about_a_big_file_but_still_runs(
    step_files: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "LARGE_BYTES", 1000)
    out = tmp_path / "out"
    r = runner.invoke(app, ["export", str(step_files["plate_4xM3"]), "-o", str(out), "--no-images"])
    assert r.exit_code == 0, r.output
    assert "will take about" in r.output and "plate_4xM3" in r.output
    assert any(out.rglob("*_SMALL.md")), "the export still ran"


def test_small_files_get_no_warning(step_files: dict[str, Path], tmp_path: Path) -> None:
    r = runner.invoke(
        app,
        ["export", str(step_files["plate_4xM3"]), "-o", str(tmp_path / "o"), "--no-images"],
    )
    assert r.exit_code == 0 and "will take about" not in r.output
