"""Reports and cache entries written before the point/line split was dropped still load.

Before 3571f9a a touching pair that is neither a face contact nor a fit had kind "point" or
"line" and a sentence "touches at a point" / "touches along a line". A user who upgrades keeps
saved reports and finished exports in the result cache; they must load (as "edge_or_point"), not
fail validation. Anything else that is wrong with a report still fails, clearly.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

import pytest
from contact_truth_fixtures import write
from pydantic import ValidationError

from stepscribe import cache, exporter
from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full, restore_analysis
from stepscribe.batch import Job, process_file
from stepscribe.models.schema import Report

NEW = "touches at an edge or point"
OLD_SENTENCE = re.compile(r"touches at an edge or point")


@pytest.fixture(scope="module")
def pair(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:  # type: ignore[type-arg]
    """A STEP file with one edge-or-point touch, and its report as JSON data."""
    step = write("edge_edge_parallel", tmp_path_factory.mktemp("old_reports"))
    report = analyze_full(step, AnalyzeOptions(understanding=False, no_timestamp=True)).report
    return step, json.loads(report.model_dump_json())


def _as_old(data: dict, kind: str = "line") -> dict:  # type: ignore[type-arg]
    """The report as the previous version wrote it."""
    old = json.loads(json.dumps(data))
    word = {"line": "touches along a line", "point": "touches at a point"}[kind]
    for c in old["assembly"]["contacts"]:
        if c["kind"] == "edge_or_point":
            c["kind"] = kind
    for r in old["assembly"]["relations"]:
        r["sentence"] = OLD_SENTENCE.sub(word, r["sentence"])
    return old


@pytest.mark.parametrize("kind", ["line", "point"])
def test_a_report_with_the_old_kinds_loads(pair, kind: str) -> None:  # type: ignore[no-untyped-def]
    _step, data = pair
    old = _as_old(data, kind)
    assert any(c["kind"] == kind for c in old["assembly"]["contacts"])
    report = Report.model_validate_json(json.dumps(old))
    assert [c.kind for c in report.assembly.contacts] == ["edge_or_point"]  # type: ignore[union-attr]
    sentences = [r.sentence for r in report.assembly.relations]  # type: ignore[union-attr]
    assert any(NEW in s for s in sentences)
    assert not any("touches at a point" in s or "touches along a line" in s for s in sentences)


def test_restore_analysis_accepts_an_old_saved_report(pair, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    step, data = pair
    saved = tmp_path / "old_report.json"
    saved.write_text(json.dumps(_as_old(data)), encoding="utf-8")
    restored = restore_analysis(step, AnalyzeOptions(no_timestamp=True), saved)
    assert [c.kind for c in restored.report.assembly.contacts] == ["edge_or_point"]  # type: ignore[union-attr]


def _job(step: Path, entry: Path) -> Job:
    opts = AnalyzeOptions(no_timestamp=True)
    return Job(
        path=str(step), out_dir=str(entry), mode="export", options=asdict(opts), images=False
    )


def _cached_export(step: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Export through the cache exactly as the MCP jobs do; returns the report.json inside it."""
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    entry = cache.entry_dir(step, AnalyzeOptions(no_timestamp=True))
    done = process_file(_job(step, entry))
    assert done["status"] == "ok", done
    return next(entry.glob("*_stepscribe")) / "data" / "report.json"


def test_an_old_cache_entry_loads_and_is_reused(pair, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    step, data = pair
    report_json = _cached_export(step, tmp_path, monkeypatch)
    report_json.write_text(
        json.dumps(_as_old(data)), encoding="utf-8"
    )  # as an older version wrote it
    opts = AnalyzeOptions(no_timestamp=True)
    cached = cache.load_report(step, opts)
    assert cached is not None  # a hit, not a miss
    assert [c.kind for c in cached.assembly.contacts] == ["edge_or_point"]  # type: ignore[union-attr]
    again = process_file(_job(step, cache.entry_dir(step, opts)))
    assert again["status"] == "ok", again  # the finished export is reused and its report loads


def test_a_corrupted_report_still_fails_clearly(pair) -> None:  # type: ignore[no-untyped-def]
    _step, data = pair
    bad_kind = json.loads(json.dumps(data))
    bad_kind["assembly"]["contacts"][0]["kind"] = "banana"
    with pytest.raises(ValidationError, match="kind"):
        Report.model_validate_json(json.dumps(bad_kind))
    missing = json.loads(json.dumps(data))
    del missing["assembly"]["contacts"][0]["min_distance_mm"]
    with pytest.raises(ValidationError, match="min_distance_mm"):
        Report.model_validate_json(json.dumps(missing))


def test_a_corrupted_cache_entry_is_a_miss_or_a_clear_error(
    pair, tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    step, data = pair
    report_json = _cached_export(step, tmp_path, monkeypatch)
    bad = json.loads(json.dumps(data))
    bad["assembly"]["contacts"][0]["kind"] = "banana"
    report_json.write_text(json.dumps(bad), encoding="utf-8")
    opts = AnalyzeOptions(no_timestamp=True)
    assert cache.load_report(step, opts) is None  # cannot be trusted: recompute
    result = process_file(_job(step, cache.entry_dir(step, opts)))
    assert result["status"] == "error" and "kind" in " ".join(result["errors"])


def test_the_export_key_includes_the_schema_version(pair, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    step, _data = pair
    opts = AnalyzeOptions(no_timestamp=True)
    before = exporter.export_key(step, opts, None, {})
    monkeypatch.setattr(exporter, "SCHEMA_VERSION", "9.9.9")
    assert (
        exporter.export_key(step, opts, None, {}) != before
    )  # a new schema never reuses an export
