"""Mass distribution and static holding loads on the generated six-axis arm: the numbers are checked
against a hand formula that reads only robot.json, and the cases that must refuse do refuse."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.pack.robot import build_robot
from stepscribe.pack.writer import write_pack
from stepscribe.understanding import mass_distribution as md
from stepscribe.understanding.rigid_body import STATIC_LABEL, G, Payload


@pytest.fixture(scope="module")
def steel_arm(step_files):  # type: ignore[no-untyped-def]
    return analyze_full(
        step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True, material="steel")
    )


@pytest.fixture(scope="module")
def bare_arm(step_files):  # type: ignore[no-untyped-def]
    return analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True))


def by_joint(data: dict) -> dict:  # type: ignore[type-arg]
    return {j["joint"]: j for j in data["static_holding_loads"]["joints"]}


def hand_torque(data: dict, joint_id: str, payload: Payload | None = None) -> float:  # type: ignore[type-arg]
    """The holding torque of one joint from robot.json alone: minus a . sum (c - o) x (m g)."""
    joints = data["joints"]
    ids = [j["id"] for j in joints]
    k = ids.index(joint_id)
    axis = np.array(joints[k]["axis"])
    origin = np.array(joints[k]["origin_mm"]) / 1000
    up = {"+X": (1, 0, 0), "+Y": (0, 1, 0), "+Z": (0, 0, 1)}[
        data["static_holding_loads"]["up_axis"]
    ]
    g = -np.array(up, float) * G
    below = {joints[k]["child"]}
    for j in joints[k + 1 :]:
        if j["parent"] in below:
            below.add(j["child"])
    moment = np.zeros(3)
    for link in data["links"]:
        if link["id"] in below:
            moment += np.cross(np.array(link["com_mm"]) / 1000 - origin, link["mass_g"] / 1000 * g)
    if payload is not None:
        tip = (np.array(joints[-1]["origin_mm"]) + payload.offset_mm) / 1000
        moment += np.cross(tip - origin, payload.mass_kg * g)
    return float(-(axis @ moment))


def test_every_joint_matches_the_hand_formula(steel_arm) -> None:  # type: ignore[no-untyped-def]
    data = build_robot(steel_arm.report)
    assert data is not None
    loads = by_joint(data)
    assert len(loads) == 6
    for jid, row in loads.items():
        assert row["value"] == pytest.approx(hand_torque(data, jid), abs=2e-6), jid
        assert row["unit"] == "N*m" and row["reason"] is None
    assert data["static_holding_loads"]["label"] == STATIC_LABEL
    assert data["static_holding_loads"]["payload"] is None


def test_the_payload_adds_exactly_its_own_moment(steel_arm) -> None:  # type: ignore[no-untyped-def]
    payload = Payload(2.5, np.array([0.0, 0.0, 150.0]))
    plain = build_robot(steel_arm.report)
    loaded = build_robot(steel_arm.report, payload)
    assert plain is not None and loaded is not None
    for jid, row in by_joint(loaded).items():
        assert row["value"] == pytest.approx(hand_torque(loaded, jid, payload), abs=2e-6), jid
    assert loaded["static_holding_loads"]["payload"]["mass_kg"] == 2.5
    changed = [
        jid
        for jid in by_joint(loaded)
        if abs(by_joint(loaded)[jid]["value"] - by_joint(plain)[jid]["value"]) > 1e-6
    ]
    assert changed, "a 2.5 kg payload must change some joint"


def test_assembly_and_links_agree_with_the_reports_own_mass_and_centre(steel_arm) -> None:  # type: ignore[no-untyped-def]
    report = steel_arm.report
    asm = report.assembly
    whole = md.assembly_body(report)
    assert not isinstance(whole, str)
    assert whole.mass_g == pytest.approx(asm.total_mass_g, rel=1e-9)
    c = asm.center_of_mass
    assert whole.com_mm == pytest.approx([c.x, c.y, c.z], abs=1e-6)
    links = [md.link_body(report, g.instance_ids) for g in report.understanding.kinematics.links]
    assert all(not isinstance(b, str) for b in links)
    again = md.combine(links)  # type: ignore[arg-type]
    assert again.inertia_g_mm2 == pytest.approx(whole.inertia_g_mm2, rel=1e-9, abs=1e-3)


def test_the_distribution_lists_parts_links_and_the_assembly(steel_arm) -> None:  # type: ignore[no-untyped-def]
    dist = md.mass_distribution(steel_arm.report)
    assert dist["assembly"]["status"] == "computed" and len(dist["links"]) == 7
    assert [p["id"] for p in dist["parts"]] == [p.id for p in steel_arm.report.parts]
    for entry in (*dist["parts"], dist["assembly"]):
        m = entry["moments_g_mm2"]
        assert m == sorted(m) and min(m) > 0 and all(k > 0 for k in entry["radii_of_gyration_mm"])
    assert "not measured" in dist["label"]


def test_no_material_means_not_computed_with_the_reason(bare_arm) -> None:  # type: ignore[no-untyped-def]
    dist = md.mass_distribution(bare_arm.report)
    assert dist["assembly"] == {"status": "not computed", "reason": "material or density unknown"}
    assert all(p["status"] == "not computed" for p in dist["parts"])
    data = build_robot(bare_arm.report)
    assert data is not None
    for row in by_joint(data).values():
        assert row["value"] is None and "not computed: mass unknown or unreliable" in row["reason"]


def test_a_part_that_is_not_a_closed_solid_is_refused(steel_arm) -> None:  # type: ignore[no-untyped-def]
    report = steel_arm.report.model_copy(deep=True)
    shell = report.parts[2]  # a link in the middle of the chain
    shell.is_valid_solid = False
    shell.topology.solids = 0
    assert md.part_body(shell) == "not computed: not a valid closed solid"
    data = build_robot(report)
    assert data is not None
    loads = by_joint(data)
    # the joints that carry that link, and everything below it, refuse; the base side is unaffected
    refused = [j for j, row in loads.items() if row["value"] is None]
    assert refused and "KJ1" in refused
    assert all("mass unknown or unreliable" in loads[j]["reason"] for j in refused)
    dist = md.mass_distribution(report)
    assert dist["parts"][2]["reason"] == "not a valid closed solid"
    assert dist["assembly"]["status"] == "not computed"


def test_complex_geometry_is_refused_for_loads_but_not_for_inertia(  # type: ignore[no-untyped-def]
    steel_arm, monkeypatch: pytest.MonkeyPatch
) -> None:
    flagged = steel_arm.report.parts[2].id  # a part of a moving link
    monkeypatch.setattr(
        md,
        "complex_geometry_reason",
        lambda p: "free-form" if p.id == flagged else None,
    )
    data = build_robot(steel_arm.report)
    assert data is not None
    loads = by_joint(data)
    assert loads["KJ1"]["value"] is None
    assert "complex or free-form geometry" in loads["KJ1"]["reason"]
    assert md.mass_distribution(steel_arm.report)["parts"][2]["status"] == "computed"


# ------------------------------------------------------------------ the designer's payload
def test_the_payload_is_read_from_the_design_context() -> None:
    p, note = md.payload_from_context({"payload": {"mass_kg": 2.5, "offset_mm": [0, 0, 150]}})
    assert note is None and p is not None and p.mass_kg == 2.5 and list(p.offset_mm) == [0, 0, 150]
    assert md.payload_from_context({}) == (None, None)
    assert md.payload_from_context({"payload": {"mass_kg": 1}})[0].offset_mm.tolist() == [0, 0, 0]  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "raw",
    [
        "heavy",
        {"offset_mm": [0, 0, 0]},
        {"mass_kg": 0},
        {"mass_kg": -1, "offset_mm": [0, 0, 0]},
        {"mass_kg": "x"},
        {"mass_kg": 1, "offset_mm": [0, 0]},
        {"mass_kg": float("inf")},
        {"mass_kg": 1, "offset_mm": [0, 0, float("nan")]},
    ],
)
def test_a_bad_payload_is_ignored_and_says_so(raw: object) -> None:
    p, note = md.payload_from_context({"payload": raw})
    assert p is None and note is not None and note.startswith("payload ignored")


# ------------------------------------------------------------------ the pack
def test_the_pack_has_the_section_robot_json_and_no_names(  # type: ignore[no-untyped-def]
    steel_arm, tmp_path: Path
) -> None:
    ctx = tmp_path / "ctx.yaml"
    ctx.write_text("payload:\n  mass_kg: 2.5\n  offset_mm: [0, 0, 150]\n", encoding="utf-8")
    folder = write_pack(steel_arm, tmp_path / "pack", context_file=ctx)
    text = (folder / "05_understanding.md").read_text("utf-8")
    assert "## Mass distribution and static load (estimates)" in text
    assert STATIC_LABEL in text and "Payload (given by the designer): 2.5 kg" in text
    assert "KJ2 (revolute): holding" in text
    robot = json.loads((folder / "robot.json").read_text("utf-8"))
    assert robot["static_holding_loads"]["payload"]["mass_kg"] == 2.5
    assert robot["links"][1]["principal_inertia"]["status"] == "computed"
    section = text.split("## Mass distribution and static load (estimates)")[1]
    for part in steel_arm.report.parts:
        assert part.name not in section


def test_a_bad_payload_in_the_pack_is_named_in_the_section(  # type: ignore[no-untyped-def]
    steel_arm, tmp_path: Path
) -> None:
    ctx = tmp_path / "ctx.yaml"
    ctx.write_text("payload:\n  mass_kg: 0\n", encoding="utf-8")
    folder = write_pack(steel_arm, tmp_path / "pack", context_file=ctx)
    text = (folder / "05_understanding.md").read_text("utf-8")
    assert "payload ignored: mass_kg must be above 0" in text
    robot = json.loads((folder / "robot.json").read_text("utf-8"))
    assert robot["static_holding_loads"]["payload"] is None
