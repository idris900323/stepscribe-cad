"""H3: the web UI keeps at most one live session, queues analyses and streams its zip."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from stepscribe.runner import RUNNER, WAIT_MESSAGE
from stepscribe.ui import server as ui_server
from stepscribe.ui.server import App, JobState, make_handler


class Ui:
    def __init__(self, app: App, base: str) -> None:
        self.app, self.base = app, base

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body or {}).encode() if method == "POST" else None
        headers = {"X-Stepscribe-Token": self.app.token}
        if method == "POST":
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if r.headers.get_content_type() == "application/json" else raw

    def start(self, step: Path, **extra: Any) -> str:
        return str(self.call("POST", "/api/start_path", {"path": str(step), **extra})["id"])

    def status(self, job: str) -> dict[str, Any]:
        return dict(self.call("GET", f"/api/status?id={job}"))

    def wait_done(self, job: str, timeout: float = 240.0) -> dict[str, Any]:
        end = time.time() + timeout
        while time.time() < end:
            s = self.status(job)
            if s["done"]:
                return s
            time.sleep(0.3)
        raise AssertionError("job did not finish")


@pytest.fixture
def ui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Ui]:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    RUNNER.set_max_jobs(1)
    app = App(tmp_path / "work", tmp_path, session_idle_s=900.0)
    app.workdir.mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield Ui(app, f"http://127.0.0.1:{httpd.server_address[1]}")
    httpd.shutdown()
    app.shutdown()


def _alive(app: App, job: str) -> bool:
    p = app.jobs[job].process
    return p is not None and p.is_alive()


def test_second_job_waits_and_both_finish(ui: Ui, step_files: dict[str, Path]) -> None:
    assert RUNNER.acquire()  # some other analysis is running
    try:
        a = ui.start(step_files["plate_4xM3"], images=False)
        b = ui.start(step_files["cube_10"], images=False)
        time.sleep(0.6)
        for job in (a, b):
            s = ui.status(job)
            assert not s["done"] and s["stage"] == "waiting" and WAIT_MESSAGE in s["message"]
            assert ui.app.jobs[job].process is None, "nothing runs while another analysis does"
    finally:
        RUNNER.release()
    for job in (a, b):
        assert ui.wait_done(job)["error"] is None


def test_a_waiting_job_can_be_cancelled(ui: Ui, step_files: dict[str, Path]) -> None:
    assert RUNNER.acquire()
    try:
        job = ui.start(step_files["plate_4xM3"], images=False)
        time.sleep(0.4)
        ui.call("POST", f"/api/cancel?id={job}")
        s = ui.wait_done(job, 20)
        assert s["error"] == "cancelled" and ui.app.jobs[job].process is None
    finally:
        RUNNER.release()


def test_only_the_newest_finished_job_keeps_a_session_process(
    ui: Ui, step_files: dict[str, Path]
) -> None:
    a = ui.start(step_files["two_link_arm"], images=False)
    assert ui.wait_done(a)["error"] is None
    assert _alive(ui.app, a), "the finished job holds its interview session"
    b = ui.start(step_files["two_link_arm"], images=False)
    assert ui.wait_done(b)["error"] is None
    end = time.time() + 15
    while _alive(ui.app, a) and time.time() < end:
        time.sleep(0.2)
    assert not _alive(ui.app, a), "starting another analysis ended the previous session"
    assert _alive(ui.app, b)
    assert sum(_alive(ui.app, j) for j in (a, b)) == 1


def test_answering_after_the_session_ended_restarts_it_from_the_saved_analysis(
    ui: Ui, step_files: dict[str, Path]
) -> None:
    a = ui.start(step_files["two_link_arm"], images=False)
    first = ui.wait_done(a)
    summary = first["result"]["understanding"]["summary"]
    b = ui.start(step_files["two_link_arm"], images=False)
    ui.wait_done(b)
    end = time.time() + 15
    while _alive(ui.app, a) and time.time() < end:
        time.sleep(0.2)
    assert not _alive(ui.app, a)
    state = ui.call("GET", f"/api/questions/next?id={a}")
    assert "error" not in state, state
    assert state["understanding"]["summary"] == summary, "same understanding as the first run"
    assert state["question"] is not None
    q = state["question"]
    done = ui.call("POST", f"/api/answers?id={a}", {"question_id": q["id"], "status": "skipped"})
    assert "error" not in done
    assert _alive(ui.app, a) and not _alive(ui.app, b), "again only one live session"


def test_idle_session_timeout_is_configurable(
    tmp_path: Path, step_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert App(tmp_path, tmp_path).session_idle_s == 15 * 60, "default: 15 minutes"
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    app = App(tmp_path / "w", tmp_path, session_idle_s=2.0)
    (tmp_path / "w").mkdir()
    state = app.start(step_files["two_link_arm"], "arm.step", {"images": False})
    end = time.time() + 240
    while not state.done and time.time() < end:
        time.sleep(0.3)
    assert state.done and not state.error
    end = time.time() + 30
    while _alive(app, state.id) and time.time() < end:
        time.sleep(0.3)
    assert not _alive(app, state.id), "a session nobody talks to ends"
    app.shutdown()


def test_old_finished_jobs_are_dropped_and_their_folders_deleted(tmp_path: Path) -> None:
    app = App(tmp_path, tmp_path, keep_jobs=5)
    for i in range(8):
        folder = tmp_path / f"job{i}"
        (folder / "out").mkdir(parents=True)
        (folder / "out" / "x.txt").write_text("x", encoding="utf-8")
        app.jobs[f"job{i}"] = JobState(f"job{i}", f"n{i}", started=float(i), done=True)
    app.jobs["busy"] = JobState("busy", "running", started=0.0)  # unfinished: never dropped
    (tmp_path / "busy").mkdir()
    app.prune()
    assert sorted(app.jobs) == ["busy", "job3", "job4", "job5", "job6", "job7"]
    assert not (tmp_path / "job0").exists() and (tmp_path / "job7").exists()
    assert (tmp_path / "busy").exists()


def test_zip_is_written_once_to_disk_and_streamed(
    ui: Ui, step_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    job = ui.start(step_files["two_plates_assembly"], images=False)
    ui.wait_done(job)
    built = {"n": 0}
    real = zipfile.ZipFile

    class Counting(real):  # type: ignore[misc, valid-type]
        def __init__(self, *a: Any, **k: Any) -> None:
            built["n"] += 1
            super().__init__(*a, **k)

    monkeypatch.setattr(ui_server.zipfile, "ZipFile", Counting)
    first = ui.call("GET", f"/api/zip?id={job}")
    target = ui.app.workdir / job / "pack.zip"
    assert target.is_file() and first == target.read_bytes()
    mtime = target.stat().st_mtime_ns
    second = ui.call("GET", f"/api/zip?id={job}")
    assert second == first and target.stat().st_mtime_ns == mtime
    assert built["n"] == 1, "the zip is reused, not rebuilt for every download"
    with zipfile.ZipFile(target) as zf:
        assert any(n.endswith("context_pack.md") for n in zf.namelist())


def test_a_changed_pack_rebuilds_the_zip(ui: Ui, step_files: dict[str, Path]) -> None:
    job = ui.start(step_files["two_plates_assembly"], images=False)
    ui.wait_done(job)
    ui.call("GET", f"/api/zip?id={job}")
    pack = Path(ui.app.jobs[job].pack or "")
    (pack / "note.md").write_text("new answers", encoding="utf-8")
    time.sleep(0.05)
    data = ui.call("GET", f"/api/zip?id={job}")
    with zipfile.ZipFile(ui.app.workdir / job / "pack.zip") as zf:
        assert any(n.endswith("note.md") for n in zf.namelist())
    assert data


def test_precheck_warns_before_the_user_confirms(ui: Ui, step_files: dict[str, Path]) -> None:
    small = ui.call("GET", "/api/precheck?size_mb=3")
    assert small["warning"] is None and small["size_mb"] == 3
    big = ui.call("GET", "/api/precheck?size_mb=90")
    assert big["warning"] and "90" in big["warning"] and big["eta_s"] > 0
    by_path = ui.call(
        "GET", "/api/precheck?path=" + urllib.request.quote(str(step_files["cube_10"]))
    )
    assert by_path["size_mb"] >= 0 and "warning" in by_path
    with pytest.raises(urllib.error.HTTPError) as e:
        ui.call("GET", "/api/precheck?path=" + urllib.request.quote(str(Path(__file__))))
    assert e.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as e2:
        ui.call("GET", "/api/precheck?size_mb=abc")
    assert e2.value.code == 400


def test_the_page_asks_for_the_warning_before_analysing(ui: Ui) -> None:
    page = urllib.request.urlopen(ui.base + "/", timeout=10).read().decode("utf-8")
    assert page.count("precheck(") >= 4 and "/api/precheck?" in page


def test_shutdown_leaves_no_worker_processes(ui: Ui, step_files: dict[str, Path]) -> None:
    job = ui.start(step_files["two_link_arm"], images=False)
    ui.wait_done(job)
    proc = ui.app.jobs[job].process
    assert proc is not None and proc.is_alive()
    ui.app.shutdown()
    assert not proc.is_alive()
