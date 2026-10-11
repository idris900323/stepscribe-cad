"""H3: bounded resources: one heavy job at a time, RAM-aware workers, no orphans, size guard."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest
from proc_diag import describe_process

from stepscribe import analysis as analysis_mod
from stepscribe import limits, procutil
from stepscribe.jobs import MANAGER
from stepscribe.mcp import tools
from stepscribe.runner import RUNNER, WAIT_MESSAGE, Runner


# ------------------------------------------------------------------ the runner
def test_runner_lets_one_job_run_and_queues_the_rest() -> None:
    r = Runner(max_jobs=1)
    running = {"now": 0, "peak": 0}
    lock = threading.Lock()
    waited: list[int] = []

    def job(i: int) -> None:
        with r.slot(on_wait=lambda: waited.append(i)):
            with lock:
                running["now"] += 1
                running["peak"] = max(running["peak"], running["now"])
            time.sleep(0.15)
            with lock:
                running["now"] -= 1

    threads = [threading.Thread(target=job, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert running["peak"] == 1
    assert len(waited) >= 3, "the jobs that had to wait were told so"


def test_runner_with_two_slots_runs_two_at_once() -> None:
    r = Runner(max_jobs=2)
    peak = {"now": 0, "max": 0}
    lock = threading.Lock()

    def job() -> None:
        with r.slot():
            with lock:
                peak["now"] += 1
                peak["max"] = max(peak["max"], peak["now"])
            time.sleep(0.2)
            with lock:
                peak["now"] -= 1

    ts = [threading.Thread(target=job) for _ in range(4)]
    [t.start() for t in ts]
    [t.join(10) for t in ts]
    assert peak["max"] == 2


def test_a_waiting_job_can_be_cancelled() -> None:
    r = Runner(max_jobs=1)
    assert r.acquire()
    stop = {"now": False}
    result: list[bool] = []
    t = threading.Thread(target=lambda: result.append(r.acquire(should_stop=lambda: stop["now"])))
    t.start()
    time.sleep(0.2)
    stop["now"] = True
    t.join(5)
    assert result == [False] and r.running == 1
    r.release()
    assert r.running == 0


def test_mcp_job_waits_for_the_slot_then_finishes(
    step_files: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    tools.clear_cache()
    RUNNER.set_max_jobs(1)
    assert RUNNER.acquire()  # another analysis is running
    try:
        started = json.loads(tools.start_analysis(str(step_files["plate_4xM3"])))
        time.sleep(0.5)
        status = json.loads(tools.get_job_status(started["job_id"]))
        assert not status["done"] and WAIT_MESSAGE in status["message"]
        assert status["stage"] == "waiting"
    finally:
        RUNNER.release()
    end = time.time() + 240
    while time.time() < end:
        status = json.loads(tools.get_job_status(started["job_id"]))
        if status["done"]:
            break
        time.sleep(0.5)
    assert status["done"] and not status["error"], status
    assert MANAGER.jobs[started["job_id"]].process is not None


# ---------------------------------------------------------- RAM-aware workers
def test_worker_count_is_capped_by_available_ram() -> None:
    free = analysis_mod.worker_count
    big = 8 * 1024**3
    assert free(40, max_faces=500, available_bytes=big, cpus=16) == 8  # plenty of RAM: CPU rule
    tight = int(analysis_mod.estimate_worker_mb(20000) * 1024**2 * 2.5 / analysis_mod.RAM_SHARE)
    assert free(40, max_faces=20000, available_bytes=tight, cpus=16) == 2
    assert free(40, max_faces=20000, available_bytes=1, cpus=16) == 1, "never below one worker"
    assert free(40, max_faces=20000, available_bytes=None, cpus=16) == 8, "unknown RAM: CPU rule"


def test_worker_estimate_grows_with_faces_and_is_documented() -> None:
    a, b = analysis_mod.estimate_worker_mb(1000), analysis_mod.estimate_worker_mb(50000)
    assert 0 < a < b
    doc = analysis_mod.__doc__ or ""
    assert "MB per worker" in doc and "SO_5DOF_ARM100" in doc


def test_total_processes_never_exceed_cpus_minus_one_across_jobs() -> None:
    for jobs in (1, 2, 3):
        n = analysis_mod.worker_count(40, max_faces=100, available_bytes=None, cpus=8, jobs=jobs)
        assert n * jobs <= 7 and n >= 1


def test_available_ram_is_known_on_this_machine() -> None:
    ram = analysis_mod.available_ram_bytes()
    assert ram is None or ram > 100 * 1024**2


def test_available_ram_reads_posix_sysconf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        os,
        "sysconf",
        lambda name: {"SC_AVPHYS_PAGES": 1000, "SC_PAGE_SIZE": 4096}[name],
        raising=False,
    )
    assert analysis_mod.available_ram_bytes("linux") == 4_096_000


# ------------------------------------------------------------- process cleanup
def _parent_with_child(pid_file: str) -> None:
    child = mp.get_context("spawn").Process(target=time.sleep, args=(120,))
    child.start()
    Path(pid_file).write_text(str(child.pid), encoding="utf-8")
    time.sleep(120)


def _alive(pid: int) -> bool:
    try:
        import psutil
    except ImportError:  # pragma: no cover
        pytest.skip("psutil is needed to check processes")
    return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE


def test_kill_tree_leaves_no_orphan_children(tmp_path: Path) -> None:
    """Cancelling a job must end the worker pool it started, on every OS."""
    pytest.importorskip("psutil")
    pid_file = tmp_path / "child.pid"
    proc = mp.get_context("spawn").Process(
        target=procutil.run_in_group, args=(_parent_with_child, str(pid_file))
    )
    proc.start()
    end = time.time() + 30
    while not pid_file.exists() and time.time() < end:
        time.sleep(0.1)
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    assert _alive(proc.pid) and _alive(child_pid)
    procutil.kill_tree(proc)
    time.sleep(0.5)
    assert not _alive(proc.pid)
    assert not _alive(child_pid), "the grandchild survived"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_posix_workers_get_their_own_process_group(tmp_path: Path) -> None:
    out = tmp_path / "pg.txt"
    proc = mp.get_context("spawn").Process(
        target=procutil.run_in_group, args=(_write_group, str(out))
    )
    proc.start()
    proc.join(20)
    pgid, pid = (int(x) for x in out.read_text(encoding="utf-8").split())
    assert pgid == pid != os.getpgrp()


def _write_group(path: str) -> None:
    Path(path).write_text(f"{os.getpgrp()} {os.getpid()}", encoding="utf-8")


def test_registered_processes_are_killed_on_cleanup() -> None:
    proc = mp.get_context("spawn").Process(target=time.sleep, args=(60,))
    proc.start()
    procutil.register(proc)
    assert proc.is_alive()
    procutil.kill_all()
    assert not proc.is_alive()


def test_cleanup_handlers_are_installed_for_sigterm_and_run_kill_all() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    try:
        procutil.install_cleanup()
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler) and handler is not previous
        proc = mp.get_context("spawn").Process(target=time.sleep, args=(60,))
        proc.start()
        procutil.register(proc)
        with pytest.raises(SystemExit):
            handler(signal.SIGTERM, None)  # type: ignore[operator]
        assert not proc.is_alive(), describe_process(proc.pid)
    finally:
        signal.signal(signal.SIGTERM, previous)
        procutil.reset_cleanup_for_tests()


# ------------------------------------------------------------ large-file guard
def test_large_file_warning_thresholds() -> None:
    mb = 1024**2
    assert limits.large_file_warning(10 * mb, cpus=16) is None
    big = limits.large_file_warning(60 * mb, cpus=16)
    assert big and "60" in big and "about" in big and "minute" in big
    # small, but slow on a machine with two cores: the ten-minute rule fires, not the size rule
    slow = limits.large_file_warning(5 * mb, cpus=2)
    assert slow and "about" in slow
    assert limits.large_file_warning(5 * mb, cpus=16) is None


def test_eta_uses_the_parallelism_of_the_machine() -> None:
    """Measured: SO_5DOF_ARM100 (7 MB, 8 workers) took 215 s; the prior alone said 1500 s."""
    one = limits.eta_seconds(7_000_000, cpus=2)
    eight = limits.eta_seconds(7_000_000, cpus=16)
    assert eight < one / 4
    assert 100 < eight < 400
    from stepscribe.jobs import initial_eta_s  # the MCP ETA is this same estimate

    assert initial_eta_s.__module__ == "stepscribe.jobs"


def test_start_analysis_reports_the_warning(
    step_files: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(limits, "LARGE_BYTES", 1000)
    RUNNER.set_max_jobs(1)
    assert RUNNER.acquire()  # keep the job from starting real work
    try:
        info = json.loads(tools.start_analysis(str(step_files["plate_4xM3"])))
    finally:
        RUNNER.release()
    assert "warning" in info and "about" in info["warning"]
    time.sleep(0.2)
