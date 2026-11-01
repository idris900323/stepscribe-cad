"""Image type 8 (standard, robots): the kinematic diagram and the joint axes on the model."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from image_helpers import fresh, has_color, non_white, pack
from PIL import Image

from stepscribe.render.extra_images import render_extra_images
from stepscribe.render.kinematics_view import ARROW
from stepscribe.render.overlay import record_text_boxes
from stepscribe.render.skeleton_view import (
    BAR,
    base_point,
    descendants,
    link_centres,
    pose_bars,
    rotate_points,
    skeleton_bars,
)


def test_a_robot_gets_both_kinematic_images_and_a_plain_part_a_note(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    arm = pack(step_files, tmp_path, "arm_6_axis", "standard")
    for name in ("kinematic_diagram", "kinematic_axes"):
        path = arm / "images" / f"{name}.png"
        assert path.is_file() and 0.02 < non_white(path) < 0.99, name
        assert max(Image.open(path).size) <= 1200
    assert has_color(arm / "images/kinematic_diagram.png", BAR) and has_color(
        arm / "images/kinematic_diagram.png", ARROW
    )
    plate = pack(step_files, tmp_path, "plate_4xM3", "standard")
    assert not (plate / "images" / "kinematic_diagram.png").exists()
    assert "kinematic diagram: not drawn, no robot or mechanism with joints was detected" in (
        plate / "images" / "INDEX.md"
    ).read_text("utf-8")


def test_the_basic_set_has_neither(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    basic = pack(step_files, tmp_path, "arm_6_axis", "basic")
    assert not (basic / "images" / "kinematic_diagram.png").exists()
    assert (basic / "images" / "kinematics_iso.png").is_file()  # the old image stays


def test_the_labels_are_joint_ids_with_the_axis_direction(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    analysis = fresh(step_files, "arm_6_axis")
    with record_text_boxes() as texts:
        render_extra_images(analysis, tmp_path, "standard", 1200, "+Z", "-Y")
    drawn = {t for t, _b, _s in texts}
    assert (
        "KJ1 (0.00, 0.00, 1.00)" in drawn and "KJ2 (0.00, 1.00, 0.00)" in drawn and "base" in drawn
    )
    index = (tmp_path / "images" / "INDEX.md").read_text("utf-8")
    assert "KJ1 revolute L0 to L1, axis (0.00, 0.00, 1.00)" in index


def test_the_skeleton_math(step_files) -> None:  # type: ignore[no-untyped-def]
    from stepscribe.render import build_scene

    analysis = fresh(step_files, "arm_6_axis")
    kin = analysis.report.understanding.kinematics  # type: ignore[union-attr]
    items = build_scene(analysis)
    centres = link_centres(kin, items)
    assert set(centres) == {g.id for g in kin.links}
    bars = skeleton_bars(kin, centres, base_point(kin, items))
    assert {b[0] for b in bars} == {g.id for g in kin.links}  # every link has a bar
    origins = [np.array([j.axis.origin.x, j.axis.origin.y, j.axis.origin.z]) for j in kin.joints]
    for _link, a, b in bars:  # every bar ends at a joint, the base or a link middle
        for p in (a, b):
            near = [
                float(np.linalg.norm(p - q))
                for q in [*origins, *centres.values(), base_point(kin, items)]
            ]
            assert min(near) < 1e-6
    assert descendants(kin, "L3") == {"L3", "L4", "L5", "L6"}
    assert descendants(kin, "L6") == {"L6"}


def test_rotating_points_about_an_axis_is_exact() -> None:
    p = np.array([[1.0, 0, 0], [0, 2.0, 0]])
    out = rotate_points(p, np.zeros(3), np.array([0, 0, 1.0]), 90)
    assert np.allclose(out, [[0, 1, 0], [-2, 0, 0]], atol=1e-9)
    about = rotate_points(
        np.array([[3.0, 1, 0]]), np.array([2.0, 1, 0]), np.array([0, 0, 2.0]), 180
    )
    assert np.allclose(about, [[1, 1, 0]], atol=1e-9)


def test_a_joint_moves_only_the_links_below_it(step_files) -> None:  # type: ignore[no-untyped-def]
    from stepscribe.render import build_scene

    analysis = fresh(step_files, "arm_6_axis")
    kin = analysis.report.understanding.kinematics  # type: ignore[union-attr]
    items = build_scene(analysis)
    bars = skeleton_bars(kin, link_centres(kin, items), base_point(kin, items))
    joint = next(j for j in kin.joints if j.parent_link == "L2" and j.child_link == "L3")
    posed = pose_bars(kin, bars, joint, 30.0)
    below = descendants(kin, "L3")
    changed = {
        link
        for (link, a0, b0), (_l, a1, b1) in zip(bars, posed, strict=True)
        if not (np.allclose(a0, a1) and np.allclose(b0, b1))
    }
    assert changed and changed <= below  # nothing above the joint moves
    assert {"L4", "L5"} <= changed  # links further down move
    # a turn of zero degrees changes nothing
    assert all(
        np.allclose(a, c) and np.allclose(b, d)
        for (_l, a, b), (_m, c, d) in zip(bars, pose_bars(kin, bars, joint, 0.0), strict=True)
    )
    with pytest.raises(StopIteration):
        next(j for j in kin.joints if j.child_link == "L99")
