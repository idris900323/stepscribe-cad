# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Process helpers shared by folder runs, the MCP server and the web UI.

Workers start part-pool children of their own. To stop all of them on every OS, a worker is
started in its own process group (POSIX) and `kill_tree` signals the whole group; on Windows it
uses ``taskkill /T``.  Every worker is also registered, so an exit or a SIGTERM stops them all.
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import Any

_registry: list[Any] = []
_lock = threading.Lock()
_installed = False


def run_in_group(target: Callable[..., None], *args: Any) -> None:
    """Process entry point: become a process group leader (POSIX), then run *target*."""
    if hasattr(os, "setpgrp"):
        try:
            os.setpgrp()
        except OSError:  # pragma: no cover - already a leader
            pass
    target(*args)


def register(proc: Any) -> None:
    """Remember a worker so `kill_all` can stop it."""
    with _lock:
        if proc not in _registry:
            _registry.append(proc)


def unregister(proc: Any) -> None:
    with _lock:
        if proc in _registry:
            _registry.remove(proc)


def _group_of(pid: int) -> int | None:
    """The worker's own process group, or None if it shares ours (then only the worker is signalled)."""
    if sys.platform == "win32":
        return None
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return None
    return None if pgid == os.getpgrp() else pgid


def kill_tree(proc: Any) -> None:
    """Stop a worker and the part-pool processes it started (terminate() alone leaves those)."""
    try:
        if proc.pid is not None and sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False
            )
        elif proc.pid is not None:
            _posix_kill(proc)
        else:
            proc.terminate()
        proc.join(timeout=10)
    except (ProcessLookupError, PermissionError):
        pass
    finally:
        unregister(proc)


def _posix_kill(proc: Any) -> None:
    """SIGTERM the worker's whole process group, then SIGKILL what is left."""
    if sys.platform == "win32":  # pragma: no cover - the Windows path uses taskkill
        proc.terminate()
        return
    pgid = _group_of(proc.pid)
    if pgid is None:
        proc.terminate()
        return
    os.killpg(pgid, signal.SIGTERM)
    proc.join(timeout=3)
    try:
        os.killpg(pgid, 0)  # still anything alive in the group (children outlive the worker)?
    except (ProcessLookupError, PermissionError):
        return
    os.killpg(pgid, signal.SIGKILL)


def kill_all() -> None:
    """Stop every registered worker (called at exit and on SIGTERM)."""
    with _lock:
        procs = list(_registry)
    for proc in procs:
        try:
            if proc.is_alive():
                kill_tree(proc)
        except (ValueError, OSError):
            pass
    with _lock:
        _registry.clear()


def _on_signal(signum: int, _frame: Any) -> None:
    kill_all()
    raise SystemExit(128 + signum)


def install_cleanup() -> None:
    """Stop all workers when this process exits or gets SIGTERM / Ctrl+Break."""
    global _installed
    if _installed:
        return
    _installed = True
    atexit.register(kill_all)
    names = ["SIGTERM"] + (["SIGBREAK"] if sys.platform == "win32" else [])
    for name in names:
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _on_signal)
        except ValueError:  # not the main thread (e.g. under a test runner thread)
            pass


CTRL_EVENTS = (0, 1, 2, 5, 6)  # Ctrl+C, Ctrl+Break, console closed, log off, shutdown
_console_refs: list[Any] = []


def make_console_handler(callback: Callable[[], None]) -> Callable[[int], bool]:
    """A Windows console-control handler: run *callback* for every event that ends the program."""

    def handler(event: int) -> bool:
        if event in CTRL_EVENTS:
            callback()
            return True
        return False

    return handler


def install_console_handler(callback: Callable[[], None]) -> Callable[[], None]:
    """Run *callback* when the console window is closed (Windows). Returns a function to undo it.

    Closing the window gives the process only a few seconds; the callback must be quick.
    """
    if sys.platform != "win32":
        return lambda: None
    import ctypes

    handler = make_console_handler(callback)
    proto = getattr(ctypes, "WINFUNCTYPE")(ctypes.c_int, ctypes.c_uint)  # noqa: B009 - Windows only
    c_handler = proto(lambda event: 1 if handler(int(event)) else 0)
    kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009 - Windows only
    kernel32.SetConsoleCtrlHandler(c_handler, True)
    _console_refs.append(c_handler)  # the C callback must stay alive while it is installed

    def remove() -> None:
        kernel32.SetConsoleCtrlHandler(c_handler, False)

    return remove


def reset_cleanup_for_tests() -> None:
    global _installed
    _installed = False
