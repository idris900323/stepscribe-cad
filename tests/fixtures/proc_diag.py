"""What a process that refused to die looks like (for assertion messages in the cleanup tests)."""

from __future__ import annotations

import subprocess
import sys

KEYS = ("Name", "State", "PPid", "NSpgid", "SigIgn", "SigBlk", "SigCgt")


def describe_process(pid: int | None) -> str:
    """One short block: state, parent, process group and signal masks of *pid*."""
    if pid is None:
        return "no pid"
    try:
        if sys.platform.startswith("linux"):
            with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
                rows = [ln.strip() for ln in fh if ln.split(":")[0] in KEYS]
            return f"pid {pid}: " + " | ".join(rows)
        if sys.platform != "win32":
            out = subprocess.run(
                ["ps", "-o", "pid,ppid,pgid,stat,command", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            return out.stdout.strip() or f"pid {pid}: not in ps"
    except OSError as exc:
        return f"pid {pid}: gone ({exc.__class__.__name__})"
    return f"pid {pid}"
