"""Several files (or a zip) through the local web UI and the MCP tools: one combined assembly.

No test here draws an image (the jobs run with images off), so every one runs on every OS."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from stepscribe.api import analyze_full
from stepscribe.mcp import tools
from stepscribe.ui.server import App, make_handler
from stepscribe.ui.worker import job_inputs

TOKEN = {"value": ""}


def headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    return {"X-Stepscribe-Token": TOKEN["value"], **(extra or {})}


@pytest.fixture
def server(tmp_path: Path):  # type: ignore[no-untyped-def]
    app = App(tmp_path, tmp_path)
    TOKEN["value"] = app.token
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    app.shutdown()


def call(url: str, data: bytes | None = None, content_type: str | None = None) -> tuple[int, dict]:  # type: ignore[type-arg]
    h = headers({"Content-Type": content_type} if content_type else None)
    req = urllib.request.Request(
        url, data=data, headers=h, method="POST" if data is not None else "GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def stage(
    base: str, path: Path, batch: str | None = None, name: str | None = None
) -> tuple[int, dict]:  # type: ignore[type-arg]
    q = f"name={name or path.name}" + (f"&batch={batch}" if batch else "")
    return call(f"{base}/api/stage?{q}", path.read_bytes(), "application/octet-stream")


def start(base: str, body: dict) -> str:  # type: ignore[type-arg]
    status, res = call(
        f"{base}/api/start_files", json.dumps({"images": 0, **body}).encode(), "application/json"
    )
    assert status == 200, res
    return str(res["id"])


def wait_done(base: str, job: str, timeout: float = 240.0) -> dict:  # type: ignore[type-arg]
    end = time.time() + timeout
    while time.time() < end:
        _status, s = call(f"{base}/api/status?id={job}")
        if s["done"]:
            return s
        time.sleep(0.3)
    raise AssertionError("job did not finish")


def make_zip(tmp_path: Path, files: list[Path], name: str = "set.zip") -> Path:
    z = tmp_path / name
    with zipfile.ZipFile(z, "w") as zf:
        for f in files:
            zf.write(f, f.name)
    return z


# ------------------------------------------------------------------ the engine: a zip is a set of files
def test_a_zip_gives_the_same_parts_as_the_files_it_holds(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    a, b = step_files["plate_4xM3"], step_files["cube_10"]
    z = make_zip(tmp_path, [a, b])
    from_zip = analyze_full(z)
    from_list = analyze_full([a, b], None, None, z.stem)
    assert [p.name for p in from_zip.report.parts] == [p.name for p in from_list.report.parts]
    assert len(from_zip.report.sources) == 2 and len(from_zip.report.parts) >= 2
    assert not from_zip.report.errors


def test_an_unsafe_zip_is_an_error_in_the_report_not_a_crash(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escape.step", step_files["cube_10"].read_bytes())
    report = analyze_full(z).report
    assert not report.parts and report.errors and "evil.zip" in str(report.errors[0]["error"])
    assert not (tmp_path.parent / "escape.step").exists()


# ------------------------------------------------------------------ the worker's input rule
def test_job_inputs_one_path_is_unchanged_and_several_paths_become_one_combined_model(  # type: ignore[no-untyped-def]
    step_files, tmp_path: Path
) -> None:
    import tempfile

    a, b = step_files["plate_4xM3"], step_files["cube_10"]
    w = tempfile.TemporaryDirectory()  # job_inputs takes the job's own work folder
    try:
        assert job_inputs({"path": str(a)}, w) == (str(a), None)
        target, name = job_inputs({"path": str(a), "paths": [str(a), str(b)]}, w)
        assert [p.name for p in target] == [a.name, b.name] and name == ""
        z = make_zip(tmp_path, [a, b])
        target, name = job_inputs({"path": str(z), "paths": [str(z)]}, w)
        assert len(target) == 2 and name == "set"
        target, name = job_inputs({"path": str(a), "paths": [str(a)]}, w)
        assert target == a and name is None
    finally:
        w.cleanup()


# ------------------------------------------------------------------ the web UI
def test_two_staged_files_run_as_one_combined_job(server: str, step_files) -> None:  # type: ignore[no-untyped-def]
    a, b = step_files["plate_4xM3"], step_files["cube_10"]
    status, first = stage(server, a)
    assert status == 200 and first["files"] == 1
    status, second = stage(server, b, first["batch"])
    assert status == 200 and second["batch"] == first["batch"] and second["files"] == 2
    job = start(server, {"batch": first["batch"]})
    s = wait_done(server, job)
    assert s["error"] is None, s["error"]
    assert s["result"]["instances"] >= 2


def test_a_zip_can_be_staged_and_run(server: str, step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    z = make_zip(tmp_path, [step_files["plate_4xM3"], step_files["cube_10"]])
    status, st = stage(server, z)
    assert status == 200
    s = wait_done(server, start(server, {"batch": st["batch"]}))
    assert s["error"] is None, s["error"]
    assert s["result"]["instances"] >= 2


def test_local_paths_are_read_in_place(server: str, step_files) -> None:  # type: ignore[no-untyped-def]
    paths = [str(step_files["plate_4xM3"]), str(step_files["cube_10"])]
    s = wait_done(server, start(server, {"paths": paths}))
    assert s["error"] is None, s["error"]
    assert s["result"]["instances"] >= 2


def test_staging_refuses_what_is_not_a_step_file_or_a_zip(server: str, tmp_path: Path) -> None:
    junk = tmp_path / "notes.txt"
    junk.write_text("hello", encoding="utf-8")
    assert stage(server, junk)[0] == 415
    fake_step = tmp_path / "fake.step"
    fake_step.write_text("not a step file", encoding="utf-8")
    assert stage(server, fake_step)[0] == 415
    fake_zip = tmp_path / "fake.zip"
    fake_zip.write_text("not a zip", encoding="utf-8")
    assert stage(server, fake_zip)[0] == 415


def test_a_bad_batch_or_path_is_a_400_with_a_plain_message(server: str, step_files) -> None:  # type: ignore[no-untyped-def]
    ok = step_files["cube_10"]
    assert stage(server, ok, "../../etc")[0] == 400
    assert stage(server, ok, "deadbeef")[0] == 400  # a batch nobody started
    for body in (
        {"batch": "not-a-batch"},
        {"batch": "deadbeef"},
        {"paths": []},
        {"paths": ["nope.step"]},
        {},
        {"paths": [5]},
    ):
        status, res = call(
            server + "/api/start_files", json.dumps(body).encode(), "application/json"
        )
        assert status == 400 and "error" in res, body


def test_the_token_is_required_for_staging(server: str) -> None:
    req = urllib.request.Request(
        server + "/api/stage?name=a.step",
        data=b"ISO-10303-21;",
        method="POST",
        headers={"Content-Type": "application/octet-stream"},
    )
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code in (401, 403)


def test_the_page_accepts_several_files_and_a_zip() -> None:
    page = (Path(__file__).resolve().parent.parent / "stepscribe/ui/index.html").read_text("utf-8")
    assert 'type="file"' in page and "multiple" in page and ".zip" in page
    assert "/api/stage" in page and "/api/start_files" in page


# ------------------------------------------------------------------ the MCP tools
def test_the_mcp_tools_accept_a_zip_as_the_path(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    z = make_zip(tmp_path, [step_files["plate_4xM3"], step_files["cube_10"]])
    tools.clear_cache()
    # the report tools only read the cache: a zip is analysed by start_analysis like any file
    started = json.loads(tools.start_analysis(str(z)))
    end = time.time() + 240
    status = json.loads(tools.get_job_status(started["job_id"]))
    while not status["done"] and time.time() < end:
        time.sleep(0.3)
        status = json.loads(tools.get_job_status(started["job_id"]))
    assert status["done"] and status["error"] is None, status
    text = tools.get_overview(str(z))
    assert "PRT001" in text and "PRT002" in text, text
    analysis = tools.get_analysis(str(z))
    assert len(analysis.report.sources) == 2
    tools.clear_cache()
