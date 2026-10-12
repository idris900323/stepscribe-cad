"""The MCP server keeps a crash log, so a native crash (VTK, OpenCASCADE) leaves a trace."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

LOG = "mcp_crash.log"


def run(code: str, cache: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "STEPSCRIBE_CACHE": str(cache), "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120
    )


def test_enabling_the_crash_log_creates_the_file_in_the_cache_folder(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    out = run(
        "from stepscribe.mcp.server import enable_crash_log; print(enable_crash_log())", cache
    )
    assert out.returncode == 0, out.stderr[-500:]
    log = cache / LOG
    assert Path(out.stdout.strip()) == log and log.is_file()
    text = log.read_text(encoding="utf-8")
    assert "stepscribe MCP server started" in text and "pid" in text


def test_a_native_crash_writes_its_stack_to_the_log(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    out = run(
        "from stepscribe.mcp.server import enable_crash_log\n"
        "enable_crash_log()\n"
        "import ctypes\n"
        "def draw():\n"
        "    ctypes.string_at(0)  # what a driver fault inside VTK looks like to Python\n"
        "draw()\n",
        cache,
    )
    assert out.returncode != 0
    text = (cache / LOG).read_text(encoding="utf-8").lower()
    assert "fatal" in text and "draw" in text, text[-500:]


def test_the_log_does_not_grow_without_limit(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / LOG).write_text("old line\n" * 300_000, encoding="utf-8")  # about 2.7 MB
    out = run("from stepscribe.mcp.server import enable_crash_log; enable_crash_log()", cache)
    assert out.returncode == 0
    assert (cache / LOG).stat().st_size < 100_000


def test_cache_commands_ignore_the_log_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stepscribe import cache

    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "c"))
    (cache.cache_root() / LOG).write_text("x" * 1000, encoding="utf-8")
    assert cache.info()["entries"] == 0
    assert cache.clear() == 0 and (cache.cache_root() / LOG).exists()


def test_the_server_entry_point_turns_it_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from stepscribe import procutil
    from stepscribe.mcp import server

    calls: list[str] = []

    class Dummy:
        def run(self) -> None:
            calls.append("run")

    monkeypatch.setattr(server, "enable_crash_log", lambda: calls.append("log") or Path("x"))
    monkeypatch.setattr(server, "build_server", lambda: Dummy())
    monkeypatch.setattr(procutil, "install_cleanup", lambda: calls.append("cleanup"))
    server.main()
    assert calls[0] == "log", "the log is on before anything else can crash"
    assert calls == ["log", "cleanup", "run"]
