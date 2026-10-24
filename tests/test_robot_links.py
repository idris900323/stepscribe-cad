"""R2: link groups from names, pivot candidates from unmatched bores, flange candidates."""

from __future__ import annotations

import math

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.models.schema import KinJoint


def axis_letter(j: KinJoint) -> str:
    d = j.axis.direction
    v = (abs(d.x), abs(d.y), abs(d.z))
    k = max(range(3), key=lambda i: v[i])
    assert v[k] > math.cos(math.radians(2.0)), (j.id, v)
    return "XYZ"[k]


def kin(analyses, name):  # type: ignore[no-untyped-def]
    u = analyses(name).report.understanding
    assert u is not None
    return u.kinematics


def test_a_six_link_arm_gives_six_revolute_joints_about_the_right_axes(analyses) -> None:  # type: ignore[no-untyped-def]
    k = kin(analyses, "arm_6_axis")
    assert len(k.links) == 7, [(g.id, g.instance_ids) for g in k.links]
    assert [j.kind for j in k.joints] == ["revolute"] * 6, [(j.id, j.kind) for j in k.joints]
    assert "".join(axis_letter(j) for j in k.joints) == "ZYYXYX"
    assert k.dof == 6 and k.topology == "serial_chain"


def test_the_prefix_in_names_does_not_matter_and_the_chain_follows_the_link_numbers(
    analyses,
) -> None:  # type: ignore[no-untyped-def]
    k = kin(analyses, "arm_6_axis")
    chain = [(j.parent_link, j.child_link) for j in k.joints]
    assert chain == [(f"L{i}", f"L{i + 1}") for i in range(6)]


def test_occurrence_labels_do_not_change_the_result(analyses) -> None:  # type: ignore[no-untyped-def]
    plain, labelled = kin(analyses, "arm_6_axis"), kin(analyses, "arm_6_axis_occurrence")
    assert "".join(axis_letter(j) for j in labelled.joints) == "ZYYXYX"
    assert [j.kind for j in labelled.joints] == [j.kind for j in plain.joints]


def test_bore_and_flange_that_agree_raise_the_confidence_and_cite_both(analyses) -> None:  # type: ignore[no-untyped-def]
    j = kin(analyses, "arm_6_axis").joints[1]  # LINK1 | LINK2: bore along Y and a Y-normal flange
    codes = {e.code for e in j.evidence}
    assert {"pivot_bore", "flange"} <= codes, codes
    assert j.confidence >= 0.7


def test_a_pivot_bore_that_disagrees_with_the_flange_normal_wins_with_lower_confidence(
    analyses,
) -> None:  # type: ignore[no-untyped-def]
    k = kin(analyses, "arm_axis_disagree")
    clevis = next(j for j in k.joints if j.kind == "revolute" and axis_letter(j) == "X")
    assert clevis.confidence < 0.7
    text = " ".join(e.text for e in clevis.evidence)
    assert "flange" in text and "disagree" in text


def test_unmatched_big_bores_are_pivot_candidates_not_confidence_zero_fasteners(analyses) -> None:  # type: ignore[no-untyped-def]
    asm = analyses("arm_6_axis").report.assembly
    assert asm is not None
    pivots = [j for j in asm.fastener_joints if j.pivot_candidate]
    assert len(pivots) == 4  # the short recess pair of joint 5 is not a pivot size
    for j in pivots:
        assert j.confidence > 0 and j.suggested_fastener is None
        assert "pivot" in j.evidence and "needs tapping" not in j.evidence


def test_small_unmatched_holes_keep_the_fastener_behaviour(analyses) -> None:  # type: ignore[no-untyped-def]
    asm = analyses("blind_clearance_assembly").report.assembly
    assert asm is not None and not any(j.pivot_candidate for j in asm.fastener_joints)


def test_named_links_that_only_rest_on_each_other_are_not_merged(analyses) -> None:  # type: ignore[no-untyped-def]
    k = kin(analyses, "named_links_resting")
    assert len(k.links) == 4, [(g.id, g.instance_ids) for g in k.links]


def test_without_useful_names_the_geometric_behaviour_is_unchanged(analyses) -> None:  # type: ignore[no-untyped-def]
    k = kin(analyses, "two_plates_assembly")
    assert len(k.links) == 1 and not k.joints


def test_a_pivot_pair_without_names_is_reported_as_a_pivot_or_press_fit_candidate(analyses) -> None:  # type: ignore[no-untyped-def]
    k = kin(analyses, "pivot_pair_assembly")
    assert [j.kind for j in k.joints] == ["revolute"]
    assert 0 < k.joints[0].confidence < 0.6
    assert "pivot or press fit candidate" in " ".join(e.text for e in k.joints[0].evidence)


def test_bolted_plates_stay_rigid(analyses) -> None:  # type: ignore[no-untyped-def]
    k = kin(analyses, "tapped_assembly")
    assert not k.joints and len(k.links) == 1


def test_the_debug_view_says_the_name_pattern_made_the_links(step_files) -> None:  # type: ignore[no-untyped-def]
    a = analyze_full(
        step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True, debug_kinematics=True)
    )
    u = a.report.understanding
    assert u is not None and u.kinematics_debug is not None
    contacts = u.kinematics_debug.contacts
    assert any(c.decision == "separate" and c.connection == "revolute" for c in contacts)
    assert all("name pattern" in c.reason for c in contacts if c.decision == "merged")


def test_a_short_unmatched_recess_pair_does_not_clamp_two_link_groups_together(analyses) -> None:  # type: ignore[no-untyped-def]
    """Joint 5 has Ø30 recesses 20 mm long in all: no screw size, shorter than the diameter.

    It is a large coaxial bore pair (a locating feature or bearing seat): not a fastener, not a
    pivot and not a clamp between named links, so the flange on the same pair decides the joint:
    a revolute about the +Y/-Y normal.
    """
    asm = analyses("arm_6_axis").report.assembly
    assert asm is not None
    (pair,) = asm.bore_pairs
    assert pair.suggested_fastener is None and pair.confidence > 0 and not pair.pivot_candidate
    assert pair not in asm.fasteners and asm.fasteners == []
    k = kin(analyses, "arm_6_axis")
    assert axis_letter(k.joints[4]) == "Y" and k.joints[4].parent_link == "L4"
