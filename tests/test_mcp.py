"""Phase 10: MCP tool functions (called directly) and server registration."""

from __future__ import annotations

from pathlib import Path

import pytest
from assembly_fixtures import Node, write_assembly
from build123d import Box, Location

from stepscribe.mcp import tools


@pytest.fixture(autouse=True)
def fresh_cache(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path_factory.mktemp("mcp_cache")))
    tools.clear_cache()


def analysed(*paths: Path) -> None:
    """Report tools read the cache, so analyse (once) the way a client does: export_pack."""
    for p in paths:
        tools.export_pack(str(p))


def test_overview_and_part(step_files) -> None:  # type: ignore[no-untyped-def]
    analysed(step_files["two_plates_assembly"])
    text = tools.get_overview(str(step_files["two_plates_assembly"]))
    assert (
        "has 2 parts (1 different)" in text
        and "60.0 (width) × 60.0 (depth) × 10.0 (height) mm" in text
    )
    part = tools.get_part(str(step_files["two_plates_assembly"]), "PRT001")
    assert "# PRT001 `Plate`" in part and "TopPlate is bolted to BasePlate" in part
    with pytest.raises(ValueError, match="not found or ambiguous"):
        tools.get_part(str(step_files["two_plates_assembly"]), "nope")


def test_list_holes_filters_by_diameter(step_files) -> None:  # type: ignore[no-untyped-def]
    analysed(step_files["nema17_plate"])
    path = str(step_files["nema17_plate"])
    assert tools.list_holes(path).count("| H0") == 5
    only_big = tools.list_holes(path, min_d=10.0)
    assert only_big.count("| H0") == 1 and "Ø22.0" in only_big
    assert tools.list_holes(path, max_d=1.0) == "No holes match."


def test_relations_and_shopping_list(step_files) -> None:  # type: ignore[no-untyped-def]
    analysed(step_files["two_plates_assembly"], step_files["plate_4xM3"])
    path = str(step_files["two_plates_assembly"])
    assert "bolted to" in tools.get_relations(path)
    assert "rests on" in tools.get_relations(path, part="Plate")
    assert "4 × M3 × 14 SHCS" in tools.get_shopping_list(path)
    assert "single part" in tools.get_relations(str(step_files["plate_4xM3"]))


def test_measure_distance_between_instances(tmp_path: Path) -> None:
    path = write_assembly(
        tmp_path / "gap.step",
        {"Cube": Box(10, 10, 10)},
        Node(
            "Gap", children=[Node("A", "Cube", Location()), Node("B", "Cube", Location((13, 0, 0)))]
        ),
    )
    assert "3.000 mm" in tools.measure_distance(str(path), "A", "B")
    with pytest.raises(ValueError, match="matches 0 instances"):
        tools.measure_distance(str(path), "A", "Z")


def test_find_parts_by_tag_and_class(step_files) -> None:  # type: ignore[no-untyped-def]
    analysed(step_files["nema17_plate"], step_files["tube"])
    assert "PRT001" in tools.find_parts(str(step_files["nema17_plate"]), "motor mount")
    assert "PRT001" in tools.find_parts(str(step_files["tube"]), "tube")
    assert "No part matches" in tools.find_parts(str(step_files["tube"]), "gearbox")


def test_section_and_render_return_png(step_files) -> None:  # type: ignore[no-untyped-def]
    text, png = tools.section(str(step_files["tube"]), "z=10")
    assert "cut area" in text and png[:4] == b"\x89PNG"
    assert tools.render_view(str(step_files["l_bracket"]), "front")[:4] == b"\x89PNG"


def test_diff_reports_changes(step_files) -> None:  # type: ignore[no-untyped-def]
    analysed(step_files["plate_4xM3"], step_files["tube"], step_files["bolt_circle"])
    same = tools.diff(str(step_files["plate_4xM3"]), str(step_files["plate_4xM3"]))
    assert "No differences" in same
    changed = tools.diff(str(step_files["tube"]), str(step_files["bolt_circle"]))
    assert "Removed part tube" in changed and "Added part bolt_circle" in changed


def test_results_are_cached_by_file_hash(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    src = step_files["cube_10"]
    copy = tmp_path / "copy.step"
    copy.write_bytes(src.read_bytes())
    a = tools.get_analysis(str(src))
    assert tools.get_analysis(str(copy)) is a, "same bytes under another name must hit the cache"


def test_server_registers_every_tool() -> None:
    pytest.importorskip("mcp.server.mcpserver")
    import asyncio

    from stepscribe.mcp.server import build_server

    listed = asyncio.run(build_server().list_tools())
    names = {t.name for t in getattr(listed, "tools", listed)}
    assert names == set(tools.TOOLS)


def test_questions_and_answers_over_the_tool_functions(step_files) -> None:  # type: ignore[no-untyped-def]
    path = str(step_files["two_link_arm"])
    text = tools.get_questions(path)
    assert "Open questions" in text and "What material" in text and "why it matters" in text
    qid = next(line.split("]")[0].lstrip("[") for line in text.splitlines() if "(material" in line)
    reply = tools.submit_answer(path, qid, "answered", "pla")
    assert "Mass updated" in reply and "Next question" in reply and "Updated summary" in reply
    assert "What material" not in tools.get_questions(path)
    with pytest.raises(ValueError, match="unknown question"):
        tools.submit_answer(path, "QNOPE00", "answered", "x")
    skipped = tools.submit_answer(path, qid, "not_sure")
    assert "Mass updated" in skipped  # a later answer replaces the earlier one


def _png_size(data: bytes) -> tuple[int, int]:
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data))
    assert img.format == "PNG"
    return img.size


def test_image_tools_return_small_pngs_and_panel_text(  # type: ignore[no-untyped-def]
    step_files, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path))
    path = str(step_files["two_plates_assembly"])
    text, png = tools.render_view_result(path, "iso")
    assert max(_png_size(png)) <= tools.MAX_IMAGE_PX and "Saved at" in text
    text, png = tools.render_view_result(path, "iso", part="PRT001")
    assert "Info panel of PRT001" in text and "overall size" in text
    assert max(_png_size(png)) <= tools.MAX_IMAGE_PX
    text, png = tools.section_result(path, "z=2.5")
    assert max(_png_size(png)) <= tools.MAX_IMAGE_PX


def test_downscale_png_keeps_small_images() -> None:
    import io

    from PIL import Image

    def make(w: int, h: int) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (w, h), "white").save(buf, format="PNG")
        return buf.getvalue()

    small = make(400, 300)
    assert tools.downscale_png(small) == small
    assert _png_size(tools.downscale_png(make(2400, 1200))) == (1200, 600)


def test_job_flow_start_poll_export(step_files, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json
    import time

    import stepscribe.exporter  # noqa: F401 - imported lazily by start_analysis; not part of the timing
    from stepscribe.jobs import MANAGER

    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path))
    path = str(step_files["two_plates_assembly"])
    started = json.loads(tools.start_analysis(path))
    # that start does not wait for the export is tested by test_start_returns_before_the_export_ends
    assert started["cached"] is False and started["eta_s"] >= 0 and started["job_id"]
    job = started["job_id"]
    status = json.loads(tools.get_job_status(job))
    deadline = time.time() + 240
    while not status["done"] and time.time() < deadline:
        assert 0 <= status["percent"] <= 100
        time.sleep(1.0)
        status = json.loads(tools.get_job_status(job))
    assert status["done"] and not status["error"], status
    assert "parts" in status["summary"]
    text = tools.export_pack(job)
    assert "two_plates_assembly_SMALL.md" in text and "----- SMALL version -----" in text
    assert "# two_plates_assembly: small version" in text
    # the same file again is served from the cache
    again = json.loads(tools.start_analysis(path))
    assert again["cached"] is True and again["eta_s"] == 0
    assert "reused from the cache" in tools.export_pack(path)
    MANAGER.jobs.clear()


def test_start_returns_before_the_export_ends(step_files, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """start_analysis hands back a job that is still running while the export is held up.

    The export is replaced by one that blocks until the test lets it go, so the property is
    "start does not wait for the export", not a wall-clock threshold that a slow runner can pass
    or miss.
    """
    import json
    import threading
    import time

    import stepscribe.exporter  # noqa: F401 - imported lazily by start_analysis
    from stepscribe.jobs import MANAGER, JobManager, JobState

    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path))
    release = threading.Event()
    entered = threading.Event()

    def slow_export(state: JobState, spec: dict, queue: object) -> None:  # type: ignore[type-arg]
        entered.set()
        release.wait(timeout=60)
        state.summary = {"parts": 0, "holes": 0, "joints": 0, "relations": 0, "seconds": 0}
        state.done = True

    monkeypatch.setattr(JobManager, "_run", staticmethod(slow_export))
    try:
        started = json.loads(tools.start_analysis(str(step_files["two_plates_assembly"])))
        assert entered.wait(timeout=30), "the held-up export never started"
        # start has already returned, and the export it started is still held up
        assert started["job_id"] and started["cached"] is False and started["eta_s"] >= 0
        status = json.loads(tools.get_job_status(started["job_id"]))
        assert status["done"] is False and status["error"] is None
        assert status["stage"] == "starting" and 0 <= status["percent"] <= 100
        # a second start for the same file while it runs reuses the running job
        again = json.loads(tools.start_analysis(str(step_files["two_plates_assembly"])))
        assert again["job_id"] == started["job_id"]
        release.set()
        end = time.time() + 30
        while not json.loads(tools.get_job_status(started["job_id"]))["done"]:
            assert time.time() < end
            time.sleep(0.05)
    finally:
        release.set()
        MANAGER.jobs.clear()


def test_export_pack_for_a_path_and_unknown_job(step_files, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path))
    text = tools.export_pack(str(step_files["plate_4xM3"]))
    assert "SMALL version" in text and "Zip:" in text
    with pytest.raises(ValueError, match="neither a job id nor a file"):
        tools.export_pack("no-such-thing")
    with pytest.raises(ValueError, match="unknown job"):
        tools.get_job_status("deadbeef")


def test_export_pack_can_save_a_copy_next_to_the_file(step_files, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    dest = tmp_path / "mine"
    text = tools.export_pack(str(step_files["plate_4xM3"]), copy_to=str(dest))
    assert "Saved a copy in:" in text
    assert any(dest.glob("*_stepscribe/*_FULL.md")) and any(dest.glob("*.zip"))
