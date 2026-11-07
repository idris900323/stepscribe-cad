"""Weak-spot text names a process only when a process is known."""

from __future__ import annotations

from pathlib import Path

import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.pack.design_context import apply_context, load_context

PROCESS_WORDS = (
    "print", "layer", "nozzle", "filament", "resin", "mould", "mold", "injection", "cnc", "milled",
    "machin", "sheet metal", "laser", "waterjet", "fdm", "sla", "sls",
)  # fmt: skip


def texts(analysis):  # type: ignore[no-untyped-def]
    u = analysis.report.understanding
    assert u is not None
    return u, [
        (w.id, f"{w.message} | {w.suggestion or ''} | {w.depends_on_assumption or ''}".lower())
        for w in u.weak_spots
    ]


def test_the_fixture_has_no_process_guess_and_sharp_corners(analyses) -> None:  # type: ignore[no-untyped-def]
    part = analyses("ribbed_sculpted").report.parts[0]
    assert part.understanding is not None
    assert part.understanding.process.ranked[0].label == "unknown"
    u, _found = texts(analyses("ribbed_sculpted"))
    assert any(w.category == "sharp_internal_corner" for w in u.weak_spots)


@pytest.mark.parametrize("name", ["ribbed_sculpted", "freeform_housing"])
def test_no_weak_spot_text_names_a_process_when_there_is_no_guess(analyses, name) -> None:  # type: ignore[no-untyped-def]
    part = analyses(name).report.parts[0]
    assert (
        part.understanding is not None and part.understanding.process.ranked[0].label == "unknown"
    )
    _u, found = texts(analyses(name))
    assert found
    for wid, text in found:
        hit = [w for w in PROCESS_WORDS if w in text]
        assert not hit, (name, wid, hit, text)


def test_a_part_guessed_to_be_printed_still_says_printed_layers(analyses) -> None:  # type: ignore[no-untyped-def]
    """The ribbed housing is guessed to be printed: the sentence about layers is true for it."""
    part = analyses("ribbed_housing").report.parts[0]
    assert part.understanding is not None
    assert part.understanding.process.ranked[0].label == "fdm_3d_printed"
    _u, found = texts(analyses("ribbed_housing"))
    corner = [t for _id, t in found if "sharp internal corner" in t]
    assert corner and "printed layers" in corner[0]


def test_a_part_the_designer_says_is_machined_does_not_split_printed_layers(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    ctx = tmp_path / "design_context.yaml"
    ctx.write_text("parts:\n  ribbed_housing:\n    process: cnc milled\n", encoding="utf-8")
    opts = AnalyzeOptions(no_timestamp=True)
    apply_context(opts, load_context(ctx))
    _u, found = texts(analyze_full(step_files["ribbed_housing"], opts))
    corner = [t for _id, t in found if "sharp internal corner" in t]
    assert corner and "layer" not in corner[0] and "print" not in corner[0]
