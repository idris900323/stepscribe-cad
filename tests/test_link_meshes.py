"""Link meshes for a digital twin: one visual and one collision STL per link, in metres, link frame."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner
from urdf_fk import parse_joints, world_frames

from stepscribe.cli import app
from stepscribe.pack.meshes import (
    MIN_TRIANGLES,
    LinkBody,
    LinkMeshes,
    box_mesh,
    convex_hull,
    file_stem,
    link_frames,
    make_link_meshes,
    mesh_health,
    mesh_of_stl,
    read_stl,
    stl_bytes,
    write_link_meshes,
)
from stepscribe.pack.robot import build_robot
from stepscribe.pack.urdf import build_urdf
from stepscribe.pack.writer import write_pack


@pytest.fixture(scope="module")
def arm(analyses):  # type: ignore[no-untyped-def]
    return analyses("arm_6_axis")


@pytest.fixture(scope="module")
def robot(arm):  # type: ignore[no-untyped-def]
    robot = build_robot(arm.report)
    assert robot is not None
    return robot


@pytest.fixture(scope="module")
def pack(arm, tmp_path_factory):  # type: ignore[no-untyped-def]
    return write_pack(arm, tmp_path_factory.mktemp("meshes"), meshes=True)


def _xyz(v):  # type: ignore[no-untyped-def]
    return [v.x, v.y, v.z]


def _refs(urdf: str) -> list[str]:
    return [m.get("filename") or "" for m in ET.fromstring(urdf).iter("mesh")]


def test_every_referenced_file_exists_and_every_link_has_both(pack: Path, robot) -> None:  # type: ignore[no-untyped-def]
    urdf = (pack / "robot.urdf").read_text(encoding="utf-8")
    refs = _refs(urdf)
    assert len(refs) == 2 * len(robot["links"]) == 14
    assert len(set(refs)) == 14
    for rel in refs:
        assert rel.startswith("meshes/") and rel.endswith(".stl"), rel
        assert (pack / rel).is_file(), rel
    root = ET.fromstring(urdf)
    for link in root.findall("link"):
        assert link.find("visual") is not None and link.find("collision") is not None
    listed = sorted(p.name for p in (pack / "meshes").iterdir() if p.suffix == ".stl")
    assert listed == sorted(Path(r).name for r in refs)
    assert (pack / "meshes" / "README.md").is_file()


def test_units_are_metres_a_known_box_gives_known_corners(pack: Path, robot) -> None:  # type: ignore[no-untyped-def]
    # the base is the box x -70..70, y -40..40, z -20..0 mm, and the base frame is the origin
    base = robot["base_link"]
    tri = read_stl((pack / f"meshes/{file_stem(base, set())}_visual.stl").read_bytes())
    pts = tri.reshape(-1, 3)
    assert np.allclose(pts.min(axis=0), [-0.070, -0.040, -0.020], atol=1e-6)
    assert np.allclose(pts.max(axis=0), [0.070, 0.040, 0.0], atol=1e-6)
    assert len(tri) == 12  # a plain box: two triangles per face


def test_mesh_plus_link_frame_equals_the_world_box_of_the_links_parts(
    pack: Path, arm, robot
) -> None:  # type: ignore[no-untyped-def]
    joints = parse_joints((pack / "robot.urdf").read_text(encoding="utf-8"))
    frames = world_frames(joints, robot["base_link"])
    boxes = {i.id: i.global_bbox for i in arm.report.assembly.instances}
    used: set[str] = set()
    for link in robot["links"]:
        stem = file_stem(link["id"], used)
        pts = read_stl((pack / f"meshes/{stem}_visual.stl").read_bytes()).reshape(-1, 3)
        world = (frames[link["id"]] @ np.vstack([pts.T, np.ones(len(pts))]))[:3].T * 1e3
        lo = np.min([_xyz(boxes[i["id"]].min) for i in link["instances"]], axis=0)
        hi = np.max([_xyz(boxes[i["id"]].max) for i in link["instances"]], axis=0)
        assert np.allclose(world.min(axis=0), lo, atol=0.05), link["id"]
        assert np.allclose(world.max(axis=0), hi, atol=0.05), link["id"]


def test_the_same_input_gives_byte_identical_files(arm, robot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    write_link_meshes(arm, robot, a)
    write_link_meshes(arm, robot, b)
    names = sorted(p.name for p in (a / "meshes").iterdir())
    assert (
        names == sorted(p.name for p in (b / "meshes").iterdir()) and len(names) == 15
    )  # 14 STL files and the README
    for n in names:
        assert (a / "meshes" / n).read_bytes() == (b / "meshes" / n).read_bytes(), n


def test_a_hostile_link_name_cannot_leave_the_meshes_folder_or_break_the_xml(
    tmp_path: Path,
) -> None:
    used: set[str] = set()
    stems = [
        file_stem(t, used)
        for t in ("../../etc/passwd", 'L0"><x/>', "CON", "", "..", "a/b\\c", "L1", "l1", "<script>")
    ]
    assert len(set(s.lower() for s in stems)) == len(
        stems
    )  # unique even when only the case differs
    for s in stems:
        assert s and all(c.isalnum() or c in "_-" for c in s), s
        assert s.upper() not in {"CON", "PRN", "AUX", "NUL"}
    robot = {
        "source": "x",
        "base_link": 'L0"><evil/>',
        "dh_style": {"rows": []},
        "warnings": [],
        "links": [{"id": 'L0"><evil/>', "instances": [], "mass_g": None}],
        "joints": [],
    }
    from stepscribe.pack.meshes import LinkMeshes

    files = {'L0"><evil/>': LinkMeshes("meshes/L0_visual.stl", 'meshes/a"b.stl', 12, 12)}
    root = ET.fromstring(build_urdf(robot, files))
    assert [e.tag for e in root.iter() if e.tag == "evil"] == []
    assert [m.get("filename") for m in root.iter("mesh")] == [
        "meshes/L0_visual.stl",
        'meshes/a"b.stl',
    ]


def test_the_triangle_cap_holds_and_every_collision_mesh_is_closed(
    arm, robot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    kinds = set()
    for cap in (12, 40, 200, 5000):
        out = tmp_path / f"cap{cap}"
        out.mkdir()
        files = write_link_meshes(arm, robot, out, cap)
        assert len(files) == 7
        for f in files.values():
            data = (out / f.collision).read_bytes()
            n = len(read_stl(data))
            assert MIN_TRIANGLES <= n <= max(cap, MIN_TRIANGLES), (cap, f.collision, n)
            assert f.collision_triangles == n
            health = mesh_health([mesh_of_stl(data)])  # one body per link in this arm
            assert (health.open_edges, health.non_manifold_edges, health.flipped_edges) == (0, 0, 0)
            assert health.volume_m3 > 0, (cap, f.collision)
            kinds.add(f.collision_kind)
    assert kinds == {"mesh", "hull"}  # the cap decides which route a link takes


def test_a_deflection_collision_mesh_has_about_the_volume_of_its_part(
    arm, robot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    files = write_link_meshes(arm, robot, tmp_path, 5000)
    volume = {p.id: p.mass.volume_mm3 for p in arm.report.parts}
    inst_part = {i.id: i.part_id for i in arm.report.assembly.instances}
    for link in robot["links"]:
        f = files[link["id"]]
        assert f.collision_kind == "mesh"  # the default cap is met by a tessellation here
        want = sum(volume[inst_part[i["id"]]] for i in link["instances"]) * 1e-9  # mm3 -> m3
        assert f.collision_health.volume_m3 == pytest.approx(want, rel=0.05), link["id"]
        assert f.visual_health.volume_m3 == pytest.approx(want, rel=0.005), link["id"]


def test_a_box_and_a_hull_of_a_point_cloud_are_closed_outward_and_within_the_cap() -> None:
    one = mesh_health([box_mesh(np.array([0.0, 0, 0]), np.array([1.0, 2, 3]))])
    assert one.closed and one.volume_m3 == pytest.approx(6.0)
    rng = np.random.default_rng(3)
    pts = rng.normal(size=(5000, 3))
    pts /= np.linalg.norm(pts, axis=1, keepdims=True)  # on a unit sphere
    sphere = 4 / 3 * np.pi
    for cap in (12, 40, 300, 1500):
        v, t = convex_hull(pts, cap)
        h = mesh_health([(v, t)])
        assert h.closed and len(t) <= cap, (cap, len(t), h)
        assert h.volume_m3 <= sphere
        if cap >= 300:
            assert h.volume_m3 > 0.9 * sphere
    grid = np.array([[x, y, z] for x in range(6) for y in range(6) for z in range(6)], dtype=float)
    v, t = convex_hull(grid, 5000)  # many points in the box faces: only the corners remain
    assert len(t) == 12 and mesh_health([(v, t)]).volume_m3 == pytest.approx(125.0)
    flat = np.array([[x, y, 0.0] for x in range(4) for y in range(4)])
    assert len(convex_hull(flat, 100)[1]) == 12  # no volume: a box rather than a crash


def _plate(holes: int):  # type: ignore[no-untyped-def]
    from build123d import Box, Cylinder, Pos

    plate = Box(200, 200, 10)
    for i in range(holes):
        for j in range(holes):
            x, y = -90 + 180 * i / (holes - 1), -90 + 180 * j / (holes - 1)
            plate -= Pos(x, y, 0) * Cylinder(3, 20)
    return plate.wrapped


def _body(shape, closed: bool = True) -> LinkBody:  # type: ignore[no-untyped-def]
    return LinkBody("INS001", "PRT001", shape, np.eye(4), 300.0, closed)


def test_a_complex_part_over_the_cap_gets_a_closed_mesh_within_it_or_a_hull_with_a_note() -> None:
    plate = _body(_plate(14))  # 196 holes: far more triangles than a small cap allows
    origin = np.zeros(3)
    big = make_link_meshes([plate], origin, 5000)
    assert big is not None and big.collision_health.closed
    assert big.collision_health.triangles <= 5000
    small = make_link_meshes([plate], origin, 300)
    assert small is not None
    assert small.collision_health.closed and small.collision_health.triangles <= 300
    assert small.collision_kind == "hull"
    assert any("convex hull" in n for n in small.notes)
    box = 0.2 * 0.2 * 0.01
    assert 0 < small.collision_health.volume_m3 <= box * 1.0001  # a hull is no bigger than the box
    holes = 196 * np.pi * 0.003**2 * 0.01
    assert small.visual_health.closed
    assert small.visual_health.volume_m3 == pytest.approx(box - holes, rel=0.01)
    again = make_link_meshes([plate], origin, 300)  # same input, same bytes
    assert again is not None
    assert stl_bytes(*small.collision) == stl_bytes(*again.collision)
    assert stl_bytes(*small.visual) == stl_bytes(*again.visual)


def test_a_visual_triangle_cap_is_met_by_coarser_tessellation_or_says_it_was_not() -> None:
    plate = _body(_plate(10))
    full = make_link_meshes([plate], np.zeros(3), 5000)
    assert full is not None and not any("visual triangle cap" in n for n in full.notes)
    n_full = full.visual_health.triangles
    capped = make_link_meshes([plate], np.zeros(3), 5000, visual_cap=n_full // 2)
    assert capped is not None
    assert capped.visual_health.triangles <= n_full // 2 and capped.visual_health.closed
    tiny = make_link_meshes([plate], np.zeros(3), 5000, visual_cap=12)
    assert tiny is not None
    assert tiny.visual_health.triangles <= 12 or any("cap 12 not met" in n for n in tiny.notes)


def test_a_source_that_is_not_closed_is_reported_not_hidden() -> None:
    from build123d import Box, Shell

    box = Box(40, 30, 20)
    open_shell = Shell(list(box.faces())[:-1]).wrapped  # a box without its top face: no solid
    res = make_link_meshes([_body(open_shell, closed=False)], np.zeros(3), 5000)
    assert res is not None
    assert res.visual_health.open_edges == 4 and not res.visual_health.closed
    assert any("because the source solid is not closed (PRT001)" in n for n in res.notes)
    assert res.collision_kind == "hull" and res.collision_health.closed
    closed = make_link_meshes([_body(box.wrapped)], np.zeros(3), 5000)
    assert closed is not None and closed.visual_health.closed
    assert not any("visual mesh not closed" in n for n in closed.notes)


def test_the_header_and_readme_name_the_links_that_use_a_hull_or_have_a_note() -> None:
    from stepscribe.pack.meshes import readme_text

    robot = {
        "source": "x",
        "base_link": "L0",
        "dh_style": {"rows": []},
        "warnings": [],
        "links": [
            {"id": "L0", "instances": [], "mass_g": None},
            {"id": "L1", "instances": [], "mass_g": None},
        ],
        "joints": [],
    }
    note = "visual mesh not closed because the source solid is not closed (PRT002): 3 open edges"
    files = {
        "L0": LinkMeshes("meshes/L0_visual.stl", "meshes/L0_collision.stl", 100, 12, 5084, 684),
        "L1": LinkMeshes(
            "meshes/L1_visual.stl", "meshes/L1_collision.stl", 900, 40, 45084, 2084, "hull",
            notes=[note],
        ),
    }  # fmt: skip
    head = build_urdf(robot, files).split("-->", 1)[0]
    assert "L0: visual 100 (5 kB), collision 12 (1 kB)" in head
    assert "L1: visual 900 (45 kB), collision: convex hull 40 (2 kB)" in head
    assert f"note: {note}" in head
    text = readme_text(robot, files, 5000, None)
    assert "| L1 | 900 |" in text and "convex hull" in text and "PRT002" in text
    assert "not capped" in text and "capped at 50 triangles" in readme_text(robot, files, 5000, 50)


def test_stl_is_binary_with_an_80_byte_header_and_the_right_size(pack: Path) -> None:
    for f in (pack / "meshes").glob("*.stl"):
        data = f.read_bytes()
        count = int(np.frombuffer(data[80:84], dtype="<u4")[0])
        assert len(data) == 84 + 50 * count, f.name
        assert not data.startswith(b"solid"), "an ASCII STL starts with 'solid'"


def test_without_meshes_nothing_is_written_and_the_urdf_has_no_mesh(
    tmp_path: Path, step_files
) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "plain"
    res = CliRunner().invoke(
        app,
        ["pack", str(step_files["arm_6_axis"]), "--out", str(out), "--no-images", "--no-timestamp"],
    )
    assert res.exit_code == 0, res.output
    assert not list(out.rglob("meshes")) and not list(out.rglob("*.stl"))
    urdf = next(out.rglob("robot.urdf")).read_text(encoding="utf-8")
    assert "<mesh" not in urdf and "<visual" not in urdf and "<collision" not in urdf
    assert "There is no visual or collision geometry in this file." in urdf


def test_the_pack_command_writes_meshes_on_request_and_ignores_them_for_a_non_robot(
    tmp_path: Path, step_files
) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "robot"
    res = CliRunner().invoke(
        app,
        ["pack", str(step_files["arm_6_axis"]), "--out", str(out), "--no-images", "--no-timestamp",
         "--meshes", "--mesh-max-triangles", "100"],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    assert len(list(out.rglob("*.stl"))) == 14
    for f in out.rglob("*_collision.stl"):
        assert len(read_stl(f.read_bytes())) <= 100
    other = tmp_path / "not_a_robot"
    res = CliRunner().invoke(
        app,
        ["pack", str(step_files["two_plates_assembly"]), "--out", str(other), "--no-images",
         "--no-timestamp", "--meshes"],
    )  # fmt: skip
    assert res.exit_code == 0, res.output
    assert not list(other.rglob("*.stl"))


def test_the_export_command_writes_meshes_on_request_only(tmp_path: Path, step_files) -> None:  # type: ignore[no-untyped-def]
    base = ["export", str(step_files["arm_6_axis"]), "--no-images", "--no-timestamp", "--no-zip"]
    plain, with_meshes = tmp_path / "plain", tmp_path / "meshes"
    assert CliRunner().invoke(app, [*base, "--out", str(plain)]).exit_code == 0
    assert not list(plain.rglob("*.stl"))
    res = CliRunner().invoke(app, [*base, "--out", str(with_meshes), "--meshes"])
    assert res.exit_code == 0, res.output
    assert len(list(with_meshes.rglob("*.stl"))) == 14
    # the chat upload set never holds a mesh
    assert not list((next(with_meshes.glob("*_stepscribe")) / "chat_bundle").glob("*.stl"))


def test_link_frames_put_the_base_at_the_origin_and_children_on_their_joint(robot) -> None:  # type: ignore[no-untyped-def]
    frames = link_frames(robot)
    assert frames[robot["base_link"]].tolist() == [0.0, 0.0, 0.0]
    for j in robot["joints"]:
        assert frames[j["child"]].tolist() == j["origin_mm"]


def test_the_export_cache_key_is_unchanged_by_default_and_follows_the_mesh_options() -> None:
    from stepscribe.exporter import _params

    plain = _params({})
    assert sorted(plain) == [
        "chat_max_images",
        "chat_max_mb",
        "compact_budget_tokens",
        "embed_images",
        "images",
        "make_zip",
        "small_budget_tokens",
    ]  # no mesh key: exports made before this option keep their cache key
    assert _params({"meshes": False, "mesh_max_triangles": 100}) == plain
    assert _params({"meshes": True})["meshes"] == 5000
    assert _params({"meshes": True, "mesh_max_triangles": 100}) != _params({"meshes": True})
    assert _params({"meshes": True, "mesh_visual_max_triangles": 800}) != _params({"meshes": True})
    assert _params({"meshes": False, "mesh_visual_max_triangles": 800}) == plain


def test_the_header_says_how_to_load_the_meshes_and_lists_their_size(pack: Path, robot) -> None:  # type: ignore[no-untyped-def]
    text = (pack / "robot.urdf").read_text(encoding="utf-8")
    head, body = text.split("-->", 1)
    assert "relative to this file" in head and "package://" in head
    for ref in _refs(text):  # relative paths only: no scheme, no drive letter, no absolute path
        assert not ref.startswith("/") and ":" not in ref and ".." not in ref, ref
    assert "package://" not in body
    used: set[str] = set()
    for link in robot["links"]:
        stem = file_stem(link["id"], used)
        for kind in ("visual", "collision"):
            data = (pack / f"meshes/{stem}_{kind}.stl").read_bytes()
            want = f"{kind} {len(read_stl(data))} ({len(data) / 1000:.0f} kB)"
            row = next(
                x for x in head.splitlines() if x.strip().startswith(f"{link['id']}: visual")
            )
            assert want in row, (row, want)
