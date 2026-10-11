"""H6: open it like an app and close it for real: one instance, Quit, heartbeat, console close."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from stepscribe import __version__, procutil
from stepscribe.ui import server as ui_server
from stepscribe.ui.server import App, IdleMonitor, JobState, make_handler


# ----------------------------------------------------------- endpoint plumbing
class Ui:
    def __init__(self, app: App, base: str, quits: list[int]) -> None:
        self.app, self.base, self.quits = app, base, quits

    def request(
        self, method: str, path: str, token: bool = True, origin: str | None = None
    ) -> tuple[int, dict[str, Any]]:
        headers: dict[str, str] = {}
        if token:
            headers["X-Stepscribe-Token"] = self.app.token
        if method == "POST":
            headers["Content-Type"] = "application/json"
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(
            self.base + path,
            data=b"{}" if method == "POST" else None,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, {}


@pytest.fixture
def ui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Ui]:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    app = App(tmp_path / "work", tmp_path)
    app.workdir.mkdir()
    quits: list[int] = []
    app.on_quit = lambda: quits.append(1)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield Ui(app, f"http://127.0.0.1:{httpd.server_address[1]}", quits)
    httpd.shutdown()
    httpd.server_close()


def test_ping_needs_the_token_and_identifies_stepscribe(ui: Ui) -> None:
    assert ui.request("GET", "/api/ping", token=False)[0] == 403
    status, body = ui.request("GET", "/api/ping")
    assert status == 200 and body["stepscribe"] is True and body["version"] == __version__


def test_heartbeat_is_recorded_and_protected(ui: Ui) -> None:
    before = ui.app.last_heartbeat
    time.sleep(0.05)
    assert ui.request("POST", "/api/heartbeat", token=False)[0] == 403
    assert ui.request("POST", "/api/heartbeat", origin="https://evil.example")[0] == 403
    assert ui.app.last_heartbeat == before
    assert ui.request("POST", "/api/heartbeat")[0] == 200
    assert ui.app.last_heartbeat > before


def test_shutdown_needs_the_token_and_a_local_origin(ui: Ui) -> None:
    assert ui.request("POST", "/api/shutdown", token=False)[0] == 403
    assert ui.request("POST", "/api/shutdown", origin="https://evil.example")[0] == 403
    assert ui.request("POST", "/api/shutdown", origin="null")[0] == 403
    time.sleep(0.3)
    assert ui.quits == [] and ui.app.workdir.exists(), "nothing was stopped"


def test_shutdown_stops_jobs_sessions_and_removes_the_work_folder(
    ui: Ui, step_files: dict[str, Path]
) -> None:
    state = ui.app.start(step_files["two_link_arm"], "arm.step", {"images": False})
    end = time.time() + 240
    while not state.done and time.time() < end:
        time.sleep(0.3)
    assert state.done and not state.error
    proc = state.process
    assert proc is not None and proc.is_alive(), "the interview session is running"
    status, body = ui.request("POST", "/api/shutdown")
    assert status == 200 and body["ok"] is True
    end = time.time() + 20
    while ui.quits == [] and time.time() < end:
        time.sleep(0.1)
    assert ui.quits == [1], "the server was told to stop exactly once"
    assert not proc.is_alive(), "no child process is left"
    assert not ui.app.workdir.exists(), "the work folder is gone"


# ---------------------------------------------------------------- idle exit
def test_an_idle_server_exits_but_not_while_an_analysis_runs(tmp_path: Path) -> None:
    app = App(tmp_path, tmp_path)
    fired: list[float] = []
    mon = IdleMonitor(app, idle_s=1.0, on_idle=lambda: fired.append(time.time()), poll_s=0.1)
    mon.start()
    try:
        time.sleep(0.5)
        assert fired == [], "not yet: the page was opened a moment ago"
        end = time.time() + 5
        while not fired and time.time() < end:
            time.sleep(0.1)
        assert len(fired) == 1, "no heartbeat for 1 s: it shuts itself down"
    finally:
        mon.stop()

    busy = App(tmp_path, tmp_path)
    busy.jobs["j"] = JobState("j", "x.step")  # an analysis that has not finished
    fired2: list[float] = []
    mon2 = IdleMonitor(busy, idle_s=1.0, on_idle=lambda: fired2.append(1.0), poll_s=0.1)
    mon2.start()
    try:
        time.sleep(2.0)
        assert fired2 == [], "never while an analysis is running"
        busy.jobs["j"].done = True
        busy.last_heartbeat = time.time()
        time.sleep(0.5)
        assert fired2 == [], "the clock starts again after the analysis"
    finally:
        mon2.stop()

    alive = App(tmp_path, tmp_path)
    fired3: list[float] = []
    mon3 = IdleMonitor(alive, idle_s=1.0, on_idle=lambda: fired3.append(1.0), poll_s=0.1)
    mon3.start()
    try:
        for _ in range(15):
            time.sleep(0.2)
            alive.last_heartbeat = time.time()
        assert fired3 == [], "a page that keeps sending heartbeats keeps the server alive"
    finally:
        mon3.stop()


# --------------------------------------------------------- one instance only
def _run_serve(tmp_path: Path, **kw: Any) -> threading.Thread:
    def target() -> None:
        ui_server.serve(
            port=kw.pop("port", 0),
            open_browser=False,
            instance_dir=tmp_path / "inst",
            **kw,
        )

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t


def _wait_lock(tmp_path: Path) -> dict[str, Any]:
    lock = tmp_path / "inst" / ui_server.LOCK_NAME
    end = time.time() + 30
    while time.time() < end:
        if lock.is_file():
            try:
                return json.loads(lock.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
            except ValueError:
                pass
        time.sleep(0.1)
    raise AssertionError("the server never wrote its lock file")


def _quit(info: dict[str, Any]) -> None:
    req = urllib.request.Request(
        f"http://127.0.0.1:{info['port']}/api/shutdown",
        data=b"{}",
        method="POST",
        headers={"X-Stepscribe-Token": info["token"], "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=30).read()


def test_a_second_start_opens_the_running_page_and_binds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    opened: list[str] = []
    monkeypatch.setattr(ui_server.webbrowser, "open", lambda url: opened.append(url) or True)
    first = _run_serve(tmp_path)
    info = _wait_lock(tmp_path)
    t0 = time.time()
    ui_server.serve(port=0, open_browser=True, instance_dir=tmp_path / "inst")
    assert time.time() - t0 < 10, "the second start returns at once"
    assert opened == [f"http://127.0.0.1:{info['port']}/"]
    assert _wait_lock(tmp_path)["port"] == info["port"], "the first server still owns the lock"
    _quit(info)
    first.join(30)
    assert not first.is_alive()
    assert not (tmp_path / "inst" / ui_server.LOCK_NAME).exists(), "the lock goes with the server"


def test_a_stale_lock_is_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    (tmp_path / "inst").mkdir()
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    port = dead.getsockname()[1]
    dead.close()  # nobody listens there
    (tmp_path / "inst" / ui_server.LOCK_NAME).write_text(
        json.dumps({"pid": 1, "port": port, "token": "old"}), encoding="utf-8"
    )
    t = _run_serve(tmp_path)
    end = time.time() + 30
    info = _wait_lock(tmp_path)
    while info["token"] == "old" and time.time() < end:
        time.sleep(0.1)
        info = _wait_lock(tmp_path)
    assert info["token"] != "old", "the dead server's lock was replaced"
    _quit(info)
    t.join(30)


def test_a_busy_port_is_not_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    busy = blocker.getsockname()[1]
    try:
        t = _run_serve(tmp_path, port=busy)
        info = _wait_lock(tmp_path)
        assert info["port"] != busy
        out = capsys.readouterr().out
        assert str(busy) in out and "busy" in out and str(info["port"]) in out
        _quit(info)
        t.join(30)
    finally:
        blocker.close()


# --------------------------------------------------------------- console close
def test_the_console_handler_runs_the_cleanup_for_every_closing_event() -> None:
    calls: list[int] = []
    handler = procutil.make_console_handler(lambda: calls.append(1))
    for event in (0, 1, 2, 5, 6):  # Ctrl+C, Ctrl+Break, window closed, log off, shutdown
        assert handler(event) is True
    assert len(calls) == 5
    assert handler(3) is False and len(calls) == 5, "other events are left alone"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console API")
def test_the_console_handler_can_be_installed_and_removed_on_windows() -> None:
    remove = procutil.install_console_handler(lambda: None)
    assert callable(remove)
    remove()


# ------------------------------------------------------------------- the page
def test_the_page_has_quit_and_sends_heartbeats(ui: Ui) -> None:
    page = urllib.request.urlopen(ui.base + "/", timeout=10).read().decode("utf-8")
    assert "Quit stepscribe" in page
    assert "/api/shutdown" in page and "/api/heartbeat" in page and "20000" in page


def test_the_ui_command_lists_the_idle_exit_option() -> None:
    from typer.testing import CliRunner

    from stepscribe.cli import app

    out = CliRunner().invoke(app, ["ui", "--help"]).output
    assert "--idle-exit-min" in out


# -------------------------------------------------------------------- the docs
def test_launcher_docs_and_readme() -> None:
    root = Path(__file__).parent.parent
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "## Desktop shortcut" in readme and "stepscribe shortcut" in readme
    for way in ("Quit", "idle", "close the window"):
        assert way.lower() in readme.lower(), way
    doc = (root / "docs" / "launcher_testing.md").read_text(encoding="utf-8")
    assert "for the user" in doc.lower() and "Task Manager" in doc and "ps " in doc


def test_real_processes_one_instance_then_quit_leaves_nothing_behind(tmp_path: Path) -> None:
    """The user path with real processes: start, start again, Quit, check for leftovers."""
    import os
    import subprocess

    psutil = pytest.importorskip("psutil")
    env = {**os.environ, "STEPSCRIBE_CACHE": str(tmp_path / "cache"), "PYTHONUTF8": "1"}
    cmd = [sys.executable, "-m", "stepscribe", "ui", "--no-browser", "--port", "0"]
    first = subprocess.Popen(
        cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        lock = tmp_path / "cache" / ui_server.LOCK_NAME
        end = time.time() + 60
        while not lock.is_file() and time.time() < end:
            time.sleep(0.2)
        info = json.loads(lock.read_text(encoding="utf-8"))
        second = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        assert second.returncode == 0 and "already running" in second.stdout
        family = [first.pid, *[c.pid for c in psutil.Process(first.pid).children(recursive=True)]]
        _quit(info)
        assert first.wait(timeout=60) == 0
        time.sleep(0.5)
        assert not [p for p in family if psutil.pid_exists(p)], (
            "a process of the first start is still running"
        )
        assert not lock.exists()
    finally:
        if first.poll() is None:
            first.kill()
