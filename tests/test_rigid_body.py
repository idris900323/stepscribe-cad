"""Principal inertia, the parallel-axis shift and the static holding load of a joint, with cases that
can be checked by hand (cube, cylinder, sphere, a two-link planar arm) and against OpenCASCADE."""

from __future__ import annotations

import math

import numpy as np
import pytest
from OCP.BRep import BRep_Builder
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.TopoDS import TopoDS_Compound

from stepscribe.geometry.properties import mass_properties
from stepscribe.understanding.rigid_body import (
    Body,
    G,
    JointSpec,
    Payload,
    combine,
    holding_loads,
    inertia_about,
    principal_inertia,
)

RHO = 7.85  # g/cm3


def body_of(shape) -> Body:  # type: ignore[no-untyped-def]
    m = mass_properties(shape, density=RHO)
    return Body(
        m.mass_g,
        np.array([m.centroid.x, m.centroid.y, m.centroid.z]),
        np.array(m.inertia_tensor_g_mm2),
    )


# ------------------------------------------------------------------ principal moments
def test_cube_has_three_equal_moments_ma2_over_6() -> None:
    a = 20.0
    b = body_of(BRepPrimAPI_MakeBox(gp_Pnt(5, 5, 5), a, a, a).Shape())
    p = principal_inertia(b.inertia_g_mm2, b.mass_g)
    m = RHO * a**3 / 1000
    assert p.moments_g_mm2 == pytest.approx([m * a * a / 6] * 3, rel=1e-9)
    assert p.radii_mm == pytest.approx([a / math.sqrt(6)] * 3, rel=1e-9)


def test_cylinder_moments_and_radii_of_gyration() -> None:
    r, h = 10.0, 40.0
    b = body_of(BRepPrimAPI_MakeCylinder(r, h).Shape())
    p = principal_inertia(b.inertia_g_mm2, b.mass_g)
    m = RHO * math.pi * r * r * h / 1000
    transverse = m * (3 * r * r + h * h) / 12
    axial = m * r * r / 2
    assert sorted(p.moments_g_mm2) == pytest.approx(
        sorted([transverse, transverse, axial]), rel=1e-6
    )
    # the axial moment has the cylinder's axis (Z) as its principal axis
    k = int(np.argmin(np.abs(p.moments_g_mm2 - axial)))
    assert abs(p.axes[k][2]) == pytest.approx(1.0, abs=1e-9)
    assert p.radii_mm[k] == pytest.approx(r / math.sqrt(2), rel=1e-6)


def test_sphere_is_two_fifths_m_r2() -> None:
    r = 15.0
    b = body_of(BRepPrimAPI_MakeSphere(gp_Pnt(30, -10, 4), r).Shape())
    p = principal_inertia(b.inertia_g_mm2, b.mass_g)
    m = RHO * 4 / 3 * math.pi * r**3 / 1000
    assert p.moments_g_mm2 == pytest.approx([0.4 * m * r * r] * 3, rel=1e-6)


def test_the_axes_are_orthonormal_and_right_handed_and_rebuild_the_tensor() -> None:
    b = body_of(BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 10, 20, 30).Shape())
    # rotate the tensor by 30 degrees about a skew axis: the moments must not change
    ax = np.array([1.0, 2.0, 3.0]) / math.sqrt(14)
    th = math.radians(30)
    k = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    rot = np.eye(3) + math.sin(th) * k + (1 - math.cos(th)) * (k @ k)
    tensor = rot @ b.inertia_g_mm2 @ rot.T
    p = principal_inertia(tensor, b.mass_g)
    assert p.moments_g_mm2 == pytest.approx([1962.5, 3925.0, 5102.5], rel=1e-9)
    assert p.axes @ p.axes.T == pytest.approx(np.eye(3), abs=1e-9)
    assert np.linalg.det(p.axes) == pytest.approx(1.0, abs=1e-9)
    assert p.axes.T @ np.diag(p.moments_g_mm2) @ p.axes == pytest.approx(tensor, abs=1e-6)


# ------------------------------------------------------------------ parallel axis
def test_the_parallel_axis_shift_adds_m_d2_on_the_perpendicular_axes() -> None:
    b = body_of(
        BRepPrimAPI_MakeBox(gp_Pnt(-5, -5, -5), 10, 10, 10).Shape()
    )  # centred at the origin
    d = 100.0
    shifted = inertia_about(np.array([d, 0.0, 0.0]), b)
    assert shifted[0, 0] == pytest.approx(b.inertia_g_mm2[0, 0], rel=1e-12)
    assert shifted[1, 1] == pytest.approx(b.inertia_g_mm2[1, 1] + b.mass_g * d * d, rel=1e-12)
    assert shifted[2, 2] == pytest.approx(b.inertia_g_mm2[2, 2] + b.mass_g * d * d, rel=1e-12)
    skew = inertia_about(np.array([30.0, 40.0, 0.0]), b)  # off-diagonal term: -m dx dy
    assert skew[0, 1] == pytest.approx(-b.mass_g * 30 * 40, rel=1e-12)


# ------------------------------------------------------------------ assembly equals OpenCASCADE
def test_two_bodies_combined_equal_opencascades_own_properties() -> None:
    s1 = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 10, 20, 30).Shape()
    s2 = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(80, 30, -10), gp_Dir(1, 1, 0)), 8, 25).Shape()
    both = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(both)
    builder.Add(both, s1)
    builder.Add(both, s2)
    whole = mass_properties(both, density=RHO)
    mine = combine([body_of(s1), body_of(s2)])
    assert mine.mass_g == pytest.approx(whole.mass_g, rel=1e-9)
    assert mine.com_mm == pytest.approx(
        [whole.centroid.x, whole.centroid.y, whole.centroid.z], rel=1e-9
    )
    assert mine.inertia_g_mm2 == pytest.approx(
        np.array(whole.inertia_tensor_g_mm2), rel=1e-6, abs=1e-6
    )


# ------------------------------------------------------------------ static holding load
def planar_arm() -> tuple[list[JointSpec], dict[str, Body | str]]:
    """Up is +Z. Joint axes are +Y; the arm lies along +X at zero angle. Lengths in mm, masses in g.

    link1: 2 kg, centre of mass at x = 250 mm; joint 2 at x = 500 mm; link2: 1 kg at x = 750 mm."""
    y = np.array([0.0, 1.0, 0.0])
    joints = [
        JointSpec("KJ1", "revolute", "L0", "L1", np.array([0.0, 0.0, 0.0]), y),
        JointSpec("KJ2", "revolute", "L1", "L2", np.array([500.0, 0.0, 0.0]), y),
    ]
    zero = np.zeros((3, 3))
    links: dict[str, Body | str] = {
        "L0": "not computed: base",  # the base is never downstream of a joint
        "L1": Body(2000.0, np.array([250.0, 0.0, 0.0]), zero),
        "L2": Body(1000.0, np.array([750.0, 0.0, 0.0]), zero),
    }
    return joints, links


UP = np.array([0.0, 0.0, 1.0])


def test_two_link_planar_arm_torques_by_hand() -> None:
    joints, links = planar_arm()
    t1, t2 = holding_loads(joints, links, UP)
    # weight of link2 about joint 2: 1 kg * g * 0.25 m; the joint must push the other way (-Y)
    assert t2.value == pytest.approx(-1.0 * G * 0.25, rel=1e-12) and t2.unit == "N*m"
    # about joint 1: 2 kg * g * 0.25 m + 1 kg * g * 0.75 m = 1.25 g
    assert t1.value == pytest.approx(-1.25 * G, rel=1e-12)
    assert t1.reason is None and t2.reason is None


def test_a_payload_adds_its_weight_at_its_offset() -> None:
    joints, links = planar_arm()
    base = holding_loads(joints, links, UP)
    loaded = holding_loads(
        joints, links, UP, Payload(mass_kg=0.5, offset_mm=np.array([100.0, 0.0, 0.0]))
    )
    # the payload sits 100 mm beyond the last joint (x = 600 mm)
    assert loaded[1].value - base[1].value == pytest.approx(-0.5 * G * 0.1, rel=1e-12)
    assert loaded[0].value - base[0].value == pytest.approx(-0.5 * G * 0.6, rel=1e-12)


def test_the_torque_is_zero_when_the_arm_hangs_straight_down() -> None:
    joints, links = planar_arm()
    down = [
        JointSpec("KJ1", "revolute", "L0", "L1", np.zeros(3), np.array([0.0, 1.0, 0.0])),
        JointSpec(
            "KJ2", "revolute", "L1", "L2", np.array([0.0, 0.0, -500.0]), np.array([0.0, 1.0, 0.0])
        ),
    ]
    links["L1"] = Body(2000.0, np.array([0.0, 0.0, -250.0]), np.zeros((3, 3)))
    links["L2"] = Body(1000.0, np.array([0.0, 0.0, -750.0]), np.zeros((3, 3)))
    t1, t2 = holding_loads(down, links, UP)
    assert t1.value == pytest.approx(0.0, abs=1e-9) and t2.value == pytest.approx(0.0, abs=1e-9)


def test_a_vertical_axis_carries_no_gravity_torque() -> None:
    joints, links = planar_arm()
    joints[0] = JointSpec("KJ1", "revolute", "L0", "L1", np.zeros(3), UP)
    t1, _t2 = holding_loads(joints, links, UP)
    assert t1.value == pytest.approx(0.0, abs=1e-9)


def test_a_prismatic_joint_holds_the_weight_it_carries() -> None:
    links: dict[str, Body | str] = {"L0": "base", "L1": Body(3000.0, np.zeros(3), np.zeros((3, 3)))}
    lift = [JointSpec("KJ1", "prismatic", "L0", "L1", np.zeros(3), UP)]
    (f,) = holding_loads(lift, links, UP)
    assert (
        f.value == pytest.approx(3.0 * G, rel=1e-12) and f.unit == "N"
    )  # pushes up against the weight


def test_unknown_mass_downstream_refuses_with_a_reason() -> None:
    joints, links = planar_arm()
    links["L2"] = "not computed: material or density unknown (part PRT003)"
    t1, t2 = holding_loads(joints, links, UP)
    assert t1.value is None and t2.value is None
    assert "not computed: mass unknown or unreliable" in t1.reason and "L2" in t1.reason


def test_a_joint_not_above_the_unknown_link_still_has_its_value() -> None:
    joints, links = planar_arm()
    links["L1"] = "unknown"  # joint 2 only carries L2
    t1, t2 = holding_loads(joints, links, UP)
    assert t1.value is None and t2.value == pytest.approx(-0.25 * G, rel=1e-12)


def test_other_joint_kinds_are_not_computed() -> None:
    joints, links = planar_arm()
    joints[1] = JointSpec("KJ2", "cylindrical", "L1", "L2", joints[1].origin_mm, joints[1].axis)
    _t1, t2 = holding_loads(joints, links, UP)
    assert t2.value is None and "cylindrical" in t2.reason


def test_a_payload_without_a_single_chain_is_refused() -> None:
    joints, links = planar_arm()
    joints.append(
        JointSpec(
            "KJ3", "revolute", "L1", "L3", np.array([500.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
        )
    )
    links["L3"] = Body(500.0, np.array([600.0, 0.0, 0.0]), np.zeros((3, 3)))
    out = holding_loads(joints, links, UP, Payload(0.5, np.zeros(3)))
    assert all(j.value is None and "payload" in j.reason for j in out)
