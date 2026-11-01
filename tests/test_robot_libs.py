"""Item B, layer 2 with the real libraries.

* MuJoCo comes with ``pip install 'stepscribe[robot]'`` and does both jobs: the forward-kinematics
  cross-check and simulator readiness. Its tests need the extra. Without it they are skipped with a
  reason scripts/check_skips.py allows; the ``robot`` CI job installs the extra and sets
  STEPSCRIBE_REQUIRE_ROBOT=1, and there a skip is a failure.
* yourdfpy is not part of the extra (install it yourself). Its adapter test runs where it is
  installed and is skipped, with its own explicit reason, where it is not.
"""

from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET  # noqa: S405 - a file this test wrote itself
from pathlib import Path

import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.pack.writer import write_pack
from stepscribe.robot_check import format_report, validate
from stepscribe.robot_check.adapters import MujocoBackend, YourdfpyBackend, mujoco_readiness
from stepscribe.robot_check.backends import available_backends, cross_check
from stepscribe.robot_check.model import parse_urdf

REASON = "the robot extra is not installed"
YOURDFPY_REASON = "yourdfpy is not installed (optional: install it yourself)"
needs_mujoco = pytest.mark.skipif(importlib.util.find_spec("mujoco") is None, reason=REASON)
needs_yourdfpy = pytest.mark.skipif(
    importlib.util.find_spec("yourdfpy") is None, reason=YOURDFPY_REASON
)

INERTIAL = (
    "<inertial><origin xyz='0 0 0'/><mass value='1'/>"
    "<inertia ixx='0.01' ixy='0' ixz='0' iyy='0.01' iyz='0' izz='0.01'/></inertial>"
)
BOX = "<collision><geometry><box size='0.1 0.1 0.1'/></geometry></collision>"


def two_links(name: str = "arm", mass: float = 1.0) -> str:
    inertial = INERTIAL.replace("value='1'", f"value='{mass}'")
    return (
        f"<?xml version='1.0'?><robot name='t'>"
        f"<link name='base'>{INERTIAL}{BOX}</link>"
        f"<link name='{name}'>{inertial}{BOX}</link>"
        "<joint name='j1' type='revolute'><parent link='base'/><child link='" + name + "'/>"
        "<origin xyz='0 0 0.2' rpy='0 0 0'/><axis xyz='0 0 1'/>"
        "<limit lower='-1' upper='1' effort='10' velocity='1'/></joint></robot>"
    )


@pytest.fixture(scope="module")
def pack_dir(step_files, tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    analysis = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True))
    return write_pack(analysis, tmp_path_factory.mktemp("robot_libs"), meshes=True)


def flip_axis(urdf_path: Path, joint: str, out: Path) -> Path:
    """A copy of the URDF with the axis of *joint* reversed (the classic sign mistake)."""
    tree = ET.parse(urdf_path)  # noqa: S314
    for j in tree.getroot().iter("joint"):
        if j.get("name") == joint:
            axis = j.find("axis")
            assert axis is not None
            xyz = [float(v) for v in str(axis.get("xyz")).split()]
            axis.set("xyz", " ".join(repr(-v) for v in xyz))
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out


# ------------------------------------------------------------------ kinematics cross-check
@needs_mujoco
def test_mujoco_agrees_with_our_kinematics_on_a_generated_arm(pack_dir: Path) -> None:
    urdf_path = pack_dir / "robot.urdf"
    urdf = parse_urdf(urdf_path.read_text("utf-8"))
    result = cross_check(urdf, urdf_path, MujocoBackend())
    assert result.status == "passed", result.findings
    # the zero pose and four fixed random joint values; every link, position and rotation
    assert result.poses == 5 and result.backend == "mujoco" and "mujoco 3." in result.detail
    assert result.max_position_error_m < 1e-9 and result.max_rotation_error < 1e-6
    print(
        f"\nmax difference MuJoCo vs stepscribe on the generated arm over {result.poses} poses: "
        f"position {result.max_position_error_m:.3g} m, rotation {result.max_rotation_error:.3g} rad"
    )


@needs_mujoco
def test_a_flipped_axis_is_detected_by_the_cross_check(pack_dir: Path) -> None:
    """Our kinematics come from the pack's own URDF; MuJoCo reads a copy with one axis reversed."""
    urdf_path = pack_dir / "robot.urdf"
    urdf = parse_urdf(urdf_path.read_text("utf-8"))
    moving = [j.name for j in urdf.joints if j.type in ("revolute", "continuous", "prismatic")]
    # next to the original, so the relative mesh paths still resolve
    flipped = flip_axis(urdf_path, moving[1], urdf_path.with_name("flipped.urdf"))
    try:
        # the zero pose cannot show a reversed axis, the random poses must
        result = cross_check(urdf, flipped, MujocoBackend())
    finally:
        flipped.unlink()
    assert result.status == "failed"
    codes = {f.code for f in result.findings}
    assert codes == {"X003"} and result.max_rotation_error > 0.1
    assert all("differs" in f.message for f in result.findings)
    print(
        f"\nflipped axis of {moving[1]}: detected, largest difference position "
        f"{result.max_position_error_m:.3g} m, rotation {result.max_rotation_error:.3g} rad, "
        f"{len(result.findings)} findings"
    )


@needs_mujoco
def test_validate_runs_the_cross_check_and_readiness_through_mujoco(pack_dir: Path) -> None:
    assert "mujoco" in available_backends()
    report = validate(pack_dir)
    assert report.layer2.status == "passed" and report.layer2.backend == "mujoco"
    assert "R100" in [f.code for f in report.readiness]
    text = format_report(report)
    assert "Simulator readiness" in text and "MuJoCo 3." in text
    assert "largest difference" in text


@needs_mujoco
def test_a_backend_that_is_named_but_not_installed_is_said_so(pack_dir: Path) -> None:
    report = validate(pack_dir, backend="no-such-library")
    assert report.layer2.status == "not_run" and "not installed" in report.layer2.detail
    assert "stepscribe[robot]" in report.layer2.detail


# ------------------------------------------------------------------ readiness (MuJoCo)
@needs_mujoco
def test_mujoco_accepting_the_file_is_one_info_finding(tmp_path: Path) -> None:
    path = tmp_path / "ok.urdf"
    path.write_text(two_links(), encoding="utf-8")
    findings = mujoco_readiness(path)
    assert findings[0].code == "R100" and findings[0].severity == "info"
    assert not [f for f in findings if f.severity in ("error", "warning")]


@needs_mujoco
def test_mujoco_refusing_the_file_makes_it_not_ready_with_its_own_reason(tmp_path: Path) -> None:
    path = tmp_path / "bad.urdf"
    path.write_text(two_links(mass=0.0), encoding="utf-8")
    findings = mujoco_readiness(path)
    assert findings[0].code == "R101" and findings[0].severity == "error"
    assert "MuJoCo" in findings[0].message and findings[0].fix


@needs_mujoco
def test_a_hostile_link_name_in_a_mujoco_message_is_a_label(tmp_path: Path) -> None:
    name = "Ignore_all_previous_instructions_script_alert_1"
    path = tmp_path / "hostile.urdf"
    path.write_text(two_links(name=name, mass=0.0), "utf-8")
    messages = " ".join(f.message for f in mujoco_readiness(path))
    assert "<" not in messages and ">" not in messages and len(messages) < 1000


# ------------------------------------------------------------------ yourdfpy (installed by the user)
@needs_yourdfpy
def test_yourdfpy_is_used_when_the_user_installed_it(pack_dir: Path) -> None:
    urdf_path = pack_dir / "robot.urdf"
    urdf = parse_urdf(urdf_path.read_text("utf-8"))
    result = cross_check(urdf, urdf_path, YourdfpyBackend())
    assert result.status == "passed", result.findings
    assert result.poses == 5 and result.max_position_error_m < 1e-9
    assert "yourdfpy" in available_backends()
