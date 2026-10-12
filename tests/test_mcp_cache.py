"""H3: the MCP server analyses a file once; report tools read the shared cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import stepscribe.api as api
import stepscribe.exporter as exporter
from stepscribe import cache
from stepscribe.analysis import AnalyzeOptions
from stepscribe.jobs import JobManager, JobState
from stepscribe.mcp import tools

REPORT_TOOLS = ("get_overview", "list_holes", "list_cutouts", "get_relations", "get_shopping_list")


@pytest.fixture
def counting(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count every analysis done in this process, wherever it is called from."""
    n = {"n": 0}
    real = api.analyze_full

    def wrapper(*a: Any, **k: Any) -> Any:
        n["n"] += 1
        return real(*a, **k)

    for mod in (api, exporter, tools):
        if hasattr(mod, "analyze_full"):
            monkeypatch.setattr(mod, "analyze_full", wrapper)
    return n


@pytest.fixture(autouse=True)
def fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    tools.clear_cache()


def test_follow_up_tools_do_zero_extra_analyses(
    step_files: dict[str, Path], counting: dict[str, int]
) -> None:
    p = str(step_files["two_plates_assembly"])
    tools.export_pack(p)
    assert counting["n"] == 1, "the export analyses once"
    tools.get_overview(p)
    tools.get_part(p, "PRT001")
    tools.list_holes(p)
    tools.list_cutouts(p)
    tools.get_relations(p)
    tools.find_parts(p, "plate")
    tools.get_shopping_list(p)
    tools.diff(p, p)
    assert counting["n"] == 1, "report-only tools must read the cache, not analyse again"


def test_report_tools_return_the_same_text_as_before(step_files: dict[str, Path]) -> None:
    p = str(step_files["two_plates_assembly"])
    tools.export_pack(p)
    text = tools.get_overview(p)
    assert "has 2 parts (1 different)" in text
    assert "# PRT001 `Plate`" in tools.get_part(p, "PRT001")
    assert "bolted to" in tools.get_relations(p)


def test_a_file_that_was_not_analysed_gets_a_message_not_a_blocking_analysis(
    step_files: dict[str, Path], counting: dict[str, int]
) -> None:
    p = str(step_files["two_plates_assembly"])
    for name in REPORT_TOOLS:
        out = getattr(tools, name)(p)
        assert "start_analysis" in out and "get_job_status" in out, name
        assert "about" in out and " s" in out, f"{name} gives the ETA"
    assert "start_analysis" in tools.get_part(p, "PRT001")
    assert "start_analysis" in tools.find_parts(p, "plate")
    assert "start_analysis" in tools.diff(p, p)
    assert counting["n"] == 0


def test_geometry_tools_keep_exactly_one_model(
    step_files: dict[str, Path], counting: dict[str, int]
) -> None:
    a, b = str(step_files["two_plates_assembly"]), str(step_files["plate_4xM3"])
    tools.get_analysis(a)
    tools.get_analysis(a)
    assert counting["n"] == 1, "the loaded model is reused"
    tools.get_analysis(b)
    assert len(tools._cache) == 1, "a different file replaces the loaded model"
    assert counting["n"] == 2


def test_model_cache_key_does_not_read_the_whole_file(
    step_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self: Path) -> bytes:
        raise AssertionError("hashing must stream the file")

    monkeypatch.setattr(Path, "read_bytes", boom)
    opts = AnalyzeOptions(no_timestamp=True)
    key = tools._key(step_files["plate_4xM3"], opts)
    assert key == cache.cache_key(step_files["plate_4xM3"], opts), "the one shared key (sha256)"


def test_job_and_session_registries_are_pruned(step_files: dict[str, Path]) -> None:
    mgr = JobManager()
    for i in range(60):
        mgr.jobs[f"j{i}"] = JobState(f"j{i}", "x.step", "out", float(i), done=True)
    mgr.jobs["running"] = JobState("running", "y.step", "out2", 1000.0)
    mgr.prune()
    assert len(mgr.jobs) <= JobManager.KEEP_FINISHED + 1
    assert "running" in mgr.jobs and "j59" in mgr.jobs and "j0" not in mgr.jobs
    for i in range(10):
        tools._sessions[f"s{i}"] = object()
    tools._prune_sessions()
    assert len(tools._sessions) <= tools.MAX_SESSIONS


def test_export_stamp_makes_the_entry_trusted(step_files: dict[str, Path]) -> None:
    p = str(step_files["plate_4xM3"])
    tools.export_pack(p)
    from stepscribe import cache

    assert cache.load_report(Path(p), AnalyzeOptions(no_timestamp=True)) is not None
    stamp = next(Path(cache.cache_root()).rglob(".stepscribe_export.json"))
    assert json.loads(stamp.read_text(encoding="utf-8"))["file_sha256"]
