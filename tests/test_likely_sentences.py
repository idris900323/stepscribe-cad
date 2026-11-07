"""Every 'Likely:' headline carries a confidence and the IDs it rests on."""

from __future__ import annotations

import re

import pytest

SUPPORT = r"\(confidence (\d\.\d\d); evidence ([^)]+)\)"


def summary(analyses, name):  # type: ignore[no-untyped-def]
    u = analyses(name).report.understanding
    assert u is not None
    return u.summary


def test_a_single_part_headline_has_confidence_and_evidence(analyses) -> None:  # type: ignore[no-untyped-def]
    s = summary(analyses, "plate_4xM3")
    m = re.match(
        r"Likely: a single plate " + SUPPORT + r", 60\.0 x 60\.0 x 5\.0 mm, 4 hole\(s\)\. "
        r"It looks laser or waterjet \(confidence 0\.64\)\.",
        s,
    )
    assert m, s  # its role (base plate, confidence 0.17) is below 0.30: no role phrase at all
    assert m.group(2) == "PRT001" and 0 < float(m.group(1)) <= 1
    assert "probably" not in s and "possibly" not in s


def test_a_static_structure_headline_has_confidence_and_evidence(analyses) -> None:  # type: ignore[no-untyped-def]
    s = summary(analyses, "two_plates_assembly")
    m = re.match(r"Likely: a static structure with no moving joints " + SUPPORT + r"\.", s)
    assert m, s
    assert m.group(1) == "0.60" and m.group(2) == "L0"


def test_a_mobile_manipulator_headline_has_confidence_evidence_and_keeps_its_joints(
    analyses,
) -> None:  # type: ignore[no-untyped-def]
    s = summary(analyses, "mini_mobile_manipulator")
    m = re.match(
        r"Likely: a mobile manipulator, a 4-wheel base \([^)]*\) carrying a \d-DOF serial arm "
        + SUPPORT
        + r": (KJ\d+ )",
        s,
    )
    assert m, s
    assert s.split("(confidence")[0].count(":") == 1  # the colon after "Likely" and no other
    u = analyses("mini_mobile_manipulator").report.understanding
    assert u is not None
    weakest = min(j.confidence for j in u.kinematics.joints)
    assert (
        float(m.group(1)) <= weakest + 0.15 + 1e-9
    )  # never above the weakest joint plus the headroom
    assert "KJ1" in m.group(2) or ".." in m.group(2)


@pytest.mark.parametrize(
    "name",
    [
        "plate_4xM3",
        "two_plates_assembly",
        "mini_mobile_manipulator",
        "tapped_assembly",
        "arm_6_axis",
        "named_links_resting",
        "two_link_arm",
        "nema17_plate",
        "pivot_pair_assembly",
    ],
)
def test_no_headline_sentence_is_left_without_confidence_and_evidence(analyses, name) -> None:  # type: ignore[no-untyped-def]
    s = summary(analyses, name)
    first = s.split(". ")[0] if name != "arm_6_axis" else s[: s.index("evidence") + 40]
    if first.startswith("Likely"):
        assert first.startswith("Likely:"), first
        assert "confidence" in first and "evidence" in first, first


# ---- the role phrase follows its confidence --------------------------------------------------------
from stepscribe.understanding.function import role_phrase  # noqa: E402


def test_the_role_phrase_thresholds_are_the_documented_ones() -> None:
    from stepscribe.features.hole_standards import load_table

    row = load_table("roles.yaml")["role_phrase"]
    assert (row["probably_min"], row["possibly_min"]) == (0.60, 0.30)
    assert "heuristic" in row["source"]


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (0.60, "probably a base plate (confidence 0.60)"),
        (0.59, "possibly a base plate (confidence 0.59)"),
        (0.30, "possibly a base plate (confidence 0.30)"),
        (0.29, None),
        (0.599, "probably a base plate (confidence 0.60)"),  # what is shown is what is compared
        (0.296, "possibly a base plate (confidence 0.30)"),
        (0.17, None),
        (0.95, "probably a base plate (confidence 0.95)"),
    ],
)
def test_the_role_phrase_boundaries(confidence: float, expected: str | None) -> None:
    assert role_phrase("base_plate", confidence) == expected


@pytest.mark.parametrize(
    "name",
    [
        "plate_4xM3",
        "nema17_plate",
        "tube",
        "l_bracket",
        "bolt_circle",
        "cube_10",
        "large_thin_plate",
    ],
)
def test_any_role_phrase_in_a_summary_matches_its_band(analyses, name) -> None:  # type: ignore[no-untyped-def]
    for word, low, high in (("probably", 0.60, 1.0), ("possibly", 0.30, 0.5999)):
        for m in re.finditer(
            word + r" an? [a-z ]+ \(confidence (\d\.\d\d)\)", summary(analyses, name)
        ):
            assert low <= float(m.group(1)) <= high, (name, m.group(0))
