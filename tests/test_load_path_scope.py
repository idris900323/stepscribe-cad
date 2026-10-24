"""Load paths are traced for the heavy parts only; the pack says so and names the parts left out."""

from __future__ import annotations

import re

from stepscribe.understanding.describe import understanding_markdown


def _u(analyses, name):  # type: ignore[no-untyped-def]
    report = analyses(name).report
    assert report.understanding is not None
    return report, report.understanding


def test_the_rule_is_a_share_threshold_not_a_top_n_cap(analyses) -> None:  # type: ignore[no-untyped-def]
    """Every non-ground part at or above the share has a path; none is dropped by a count."""
    _r, u = _u(analyses, "arm_6_axis")
    traced = {lp.load_source for lp in u.load_paths}
    assert traced, "the arm fixture has heavy links"
    note = u.load_path_note
    assert re.search(r"at least \d+(\.\d+)?%", note), note
    assert "heaviest" not in note and "top" not in note.lower()


def test_the_note_names_every_part_without_a_path(analyses) -> None:  # type: ignore[no-untyped-def]
    report, u = _u(analyses, "arm_6_axis")
    assert report.assembly is not None
    traced = {lp.load_source for lp in u.load_paths}
    on_a_path = {i for lp in u.load_paths for i in lp.path}
    names = {p.id: p.name for p in report.parts}
    left_out = [
        names[i.part_id]
        for i in report.assembly.instances
        if i.id not in traced and i.id not in on_a_path
    ]
    for name in left_out:
        assert name in u.load_path_note, (name, u.load_path_note)


def test_a_traced_part_is_not_listed_as_left_out(analyses) -> None:  # type: ignore[no-untyped-def]
    report, u = _u(analyses, "arm_6_axis")
    assert report.assembly is not None
    names = {p.id: p.name for p in report.parts}
    by_id = {i.id: names[i.part_id] for i in report.assembly.instances}
    left = u.load_path_note.split("not traced:", 1)[-1]
    for lp in u.load_paths:
        assert by_id[lp.load_source] not in left


def test_the_markdown_prints_the_note_under_load_paths(analyses) -> None:  # type: ignore[no-untyped-def]
    report, u = _u(analyses, "arm_6_axis")
    text = understanding_markdown(report)
    section = text.split("## Load paths", 1)[1].split("## Weak spots", 1)[0]
    assert u.load_path_note and u.load_path_note in section


def test_no_note_without_load_paths(analyses) -> None:  # type: ignore[no-untyped-def]
    _r, u = _u(analyses, "two_plates_assembly")
    if not u.load_paths:
        assert u.load_path_note == ""
