"""Opt-in stage timings: `--timings` writes data/timings.json and changes nothing else."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stepscribe import timings
from stepscribe.cli import app

runner = CliRunner()


def _export(step: Path, out: Path, *flags: str) -> Path:
    res = runner.invoke(app, ["export", str(step), "--out", str(out), "--no-images", *flags])
    assert res.exit_code == 0, res.output
    return next(out.glob("*_stepscribe"))


def test_off_by_default_costs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STEPSCRIBE_TIMINGS", raising=False)
    assert not timings.enabled()
    with timings.stage("anything"):
        pass
    timings.add_part("p", 10, 1.0)
    timings.count("pairs", 3)
    assert timings.snapshot() == {"stages_s": {}, "parts": [], "counts": {}}


def test_flag_writes_stage_times_and_parts(
    step_files: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STEPSCRIBE_TIMINGS", raising=False)
    folder = _export(step_files["two_plates_assembly"], tmp_path / "o", "--timings")
    data = json.loads((folder / "data" / "timings.json").read_text(encoding="utf-8"))
    for name in ("load", "parts", "assembly", "assembly.contacts", "understanding"):
        assert data["stages_s"][name] >= 0.0, name
    assert data["parts"] and {"part", "faces", "seconds"} <= set(data["parts"][0])
    assert data["counts"]["contact_pairs_all"] == 1
    assert data["counts"]["contact_pairs_tested"] == 1
    assert data["total_s"] > 0


def test_the_report_is_the_same_with_and_without_timings(
    step_files: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STEPSCRIBE_TIMINGS", raising=False)
    src = step_files["two_plates_assembly"]
    plain = _export(src, tmp_path / "a")
    monkeypatch.delenv("STEPSCRIBE_TIMINGS", raising=False)
    timed = _export(src, tmp_path / "b", "--timings")
    assert not (plain / "data" / "timings.json").exists()

    def report(folder: Path) -> dict:  # type: ignore[type-arg]
        d = json.loads((folder / "data" / "report.json").read_text(encoding="utf-8"))
        d["meta"].pop("generated_at", None)
        return d  # type: ignore[no-any-return]

    assert report(plain) == report(timed)
