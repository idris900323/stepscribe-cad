"""H4: learned role models run only when the user switches them on, and the pack says which."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.understanding import ml_roles


class FakeEntryPoint:
    def __init__(self, name: str, fn: Any, dist: str = "fake-dist", version: str = "1.2.3") -> None:
        self.name, self._fn, self.loaded = name, fn, 0
        self.dist = SimpleNamespace(name=dist, version=version)

    def load(self) -> Any:
        self.loaded += 1
        if isinstance(self._fn, Exception):
            raise self._fn
        return self._fn


def counterweight(part: Any) -> dict[str, float]:
    return {"counterweight": 0.9}


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeEntryPoint]:
    eps = {
        "fake": FakeEntryPoint("fake", counterweight),
        "other": FakeEntryPoint("other", counterweight, dist="other-dist", version="9.9"),
        "broken": FakeEntryPoint("broken", RuntimeError("boom")),
    }
    monkeypatch.setattr(ml_roles, "entry_points", lambda **kw: list(eps.values()))
    monkeypatch.delenv("STEPSCRIBE_ML", raising=False)
    return eps


def test_nothing_is_loaded_by_default(installed: dict[str, FakeEntryPoint]) -> None:
    assert ml_roles.load_role_models() == {}
    assert ml_roles.load_enabled().info == []
    assert all(ep.loaded == 0 for ep in installed.values()), "no third-party code was imported"


def test_the_environment_enables_only_the_named_models(
    installed: dict[str, FakeEntryPoint], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STEPSCRIBE_ML", "fake")
    loaded = ml_roles.load_enabled()
    assert list(loaded.models) == ["fake"]
    assert loaded.info == [{"name": "fake", "distribution": "fake-dist", "version": "1.2.3"}]
    assert installed["other"].loaded == 0 and installed["broken"].loaded == 0


def test_the_design_context_enables_models_too(installed: dict[str, FakeEntryPoint]) -> None:
    loaded = ml_roles.load_enabled({"ml": {"enabled": ["other"]}})
    assert list(loaded.models) == ["other"] and loaded.info[0]["distribution"] == "other-dist"
    both = ml_roles.load_enabled(
        {"ml": {"enabled": ["other"]}}, env={"STEPSCRIBE_ML": "fake, other"}
    )
    assert sorted(both.models) == ["fake", "other"]


def test_unknown_and_broken_models_are_reported_not_fatal(
    installed: dict[str, FakeEntryPoint],
) -> None:
    loaded = ml_roles.load_enabled(env={"STEPSCRIBE_ML": "fake,missing,broken"})
    assert list(loaded.models) == ["fake"]
    assert sorted(loaded.problems) == ["broken", "missing"]


def test_analysis_records_and_prints_the_models_it_used(
    installed: dict[str, FakeEntryPoint],
    monkeypatch: pytest.MonkeyPatch,
    step_files: dict[str, Path],
) -> None:
    from stepscribe.understanding.describe import understanding_markdown

    plain = analyze_full(step_files["two_link_arm"], AnalyzeOptions(no_timestamp=True)).report
    assert "ml_models" not in plain.meta.options
    assert "Learned role models" not in understanding_markdown(plain)
    assert all(ep.loaded == 0 for ep in installed.values())

    monkeypatch.setenv("STEPSCRIBE_ML", "fake")
    report = analyze_full(step_files["two_link_arm"], AnalyzeOptions(no_timestamp=True)).report
    assert report.meta.options["ml_models"] == [
        {"name": "fake", "distribution": "fake-dist", "version": "1.2.3"}
    ]
    text = understanding_markdown(report)
    assert "Learned role models" in text and "fake-dist 1.2.3" in text
    evidence = [
        e.code
        for p in report.parts
        if p.understanding
        for r in p.understanding.roles
        for e in r.evidence
    ]
    assert "ml:fake" in evidence


def test_the_docs_say_models_are_opt_in() -> None:
    doc = (Path(__file__).parent.parent / "docs" / "future_ml.md").read_text(encoding="utf-8")
    assert "STEPSCRIBE_ML" in doc and "ml.enabled" in doc
