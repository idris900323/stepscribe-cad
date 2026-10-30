"""The pool size is logged with the rule that chose it; the numbers themselves do not change."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stepscribe import analysis as A
from stepscribe import timings
from stepscribe.api import analyze_full
from stepscribe.progress import Progress, Tracker

GB = 1024**3


@pytest.mark.parametrize("parts", [1, 5, 16, 100])
@pytest.mark.parametrize("faces", [0, 300, 1581, 40000])
@pytest.mark.parametrize("free", [None, GB, 2 * GB, 6 * GB, 64 * GB])
@pytest.mark.parametrize("cpus", [2, 4, 16])
@pytest.mark.parametrize("jobs", [1, 2])
def test_worker_count_is_the_choice_and_nothing_else_changed(
    parts, faces, free, cpus, jobs
) -> None:  # type: ignore[no-untyped-def]
    choice = A.worker_choice(parts, faces, free, cpus, jobs)
    assert A.worker_count(parts, faces, free, cpus, jobs) == choice.workers >= 1
    assert choice.workers <= max(1, parts)


def test_the_rule_names_the_limit_that_decided(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STEPSCRIBE_WORKERS", raising=False)
    cpu = A.worker_choice(100, 1000, 64 * GB, cpus=4, jobs=1)
    assert (cpu.workers, cpu.rule) == (3, "cpu") and cpu.memory_cap is not None
    mem = A.worker_choice(100, 1581, 2 * GB, cpus=16, jobs=1)
    assert mem.rule == "free memory" and mem.workers == mem.memory_cap < mem.cpu_cap
    unknown = A.worker_choice(100, 1000, None, cpus=16, jobs=1)
    assert (unknown.workers, unknown.rule) == (4, "unknown free memory")
    assert unknown.memory_cap == 4 and unknown.free_bytes is None


def test_the_environment_override_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEPSCRIBE_WORKERS", "6")
    c = A.worker_choice(100, 40000, 1 * GB, cpus=16, jobs=1)
    assert (c.workers, c.rule) == (6, "STEPSCRIBE_WORKERS")


def test_the_description_has_pool_free_memory_and_rule() -> None:
    text = A.worker_choice(100, 1581, 2 * GB, cpus=16, jobs=1).describe()
    assert text.startswith("part workers: 2 (free memory;") and "free memory 2.0 GiB" in text
    assert "cpu allows" in text and "jobs 1" in text
    assert "free memory unknown" in A.worker_choice(100, 1000, None, cpus=16, jobs=1).describe()


def test_the_pool_is_logged_in_the_progress_and_in_timings(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    seen: list[Progress] = []
    timings.enable()
    timings.reset()
    try:
        analyze_full(
            step_files["arm_6_axis"], A.AnalyzeOptions(no_timestamp=True), Tracker(seen.append)
        )
        data = timings.snapshot()
    finally:
        import os

        os.environ.pop(timings.ENV, None)
        timings.reset()
    assert any(p.message.startswith("part workers:") for p in seen)
    note = data["notes"]["part_workers"]
    assert note.startswith("part workers:") and "free memory" in note and "jobs" in note
    assert data["counts"]["part_workers"] >= 1
    out = tmp_path / "t.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    assert "part_workers" in json.loads(out.read_text("utf-8"))["notes"]
