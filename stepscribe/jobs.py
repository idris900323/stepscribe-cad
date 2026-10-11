# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Background analysis jobs for clients with short call timeouts (the MCP server).

A job runs one export in a separate process, so a start call returns at once and the client polls
for progress. Results are cached on disk by file hash and options, so asking again is instant.
Nothing here imports the web UI.
"""

from __future__ import annotations

import multiprocessing as mp
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from stepscribe import cache, limits, procutil
from stepscribe.analysis import AnalyzeOptions
from stepscribe.progress import Progress
from stepscribe.runner import RUNNER, WAIT_MESSAGE


def cache_dir() -> Path:
    """Where exports of MCP jobs live: the shared per-user cache (``STEPSCRIBE_CACHE`` overrides)."""
    return cache.cache_root()


def job_out_dir(path: Path, options: AnalyzeOptions) -> Path:
    """Cache folder for one file and one set of options (the key every front end shares)."""
    return cache.entry_dir(path, options)


def initial_eta_s(path: Path) -> float:
    """A rough first estimate from the file size; the running job replaces it with a measured one."""
    return round(limits.eta_seconds(path.stat().st_size), 0)


def _worker(spec: dict[str, Any], queue: Any) -> None:
    from stepscribe.batch import Job, process_file

    def push(p: Progress) -> None:
        queue.put(
            {
                "type": "progress",
                "stage": p.stage,
                "message": p.message,
                "fraction": p.fraction,
                "elapsed_s": p.elapsed_s,
                "eta_s": p.eta_s,
            }
        )

    try:
        summary = process_file(Job(**spec), push)
        queue.put({"type": "done", "summary": summary})
    except Exception as exc:  # noqa: BLE001
        queue.put(
            {
                "type": "error",
                "message": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=5),
            }
        )


@dataclass
class JobState:
    """One running or finished job."""

    id: str
    path: str
    out_dir: str
    started: float
    process: Any = None
    queue: Any = None
    last: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] | None = None
    error: str | None = None
    done: bool = False
    cancelled: bool = False


class JobManager:
    """Starts export jobs in worker processes and reports their progress."""

    KEEP_FINISHED = 20  # finished jobs remembered; the export itself stays in the cache

    def __init__(self) -> None:
        self.jobs: dict[str, JobState] = {}

    def prune(self) -> None:
        """Forget the oldest finished jobs; running jobs are never dropped."""
        finished = sorted((s for s in self.jobs.values() if s.done), key=lambda s: s.started)
        for state in finished[: max(0, len(finished) - self.KEEP_FINISHED)]:
            del self.jobs[state.id]

    def start(
        self,
        path: str | Path,
        options: AnalyzeOptions,
        export_params: dict[str, Any] | None = None,
        images: bool = True,
    ) -> JobState:
        """Begin an export of *path*; reuse a running job for the same file and options."""
        p = Path(path)
        out = job_out_dir(p, options)
        for state in self.jobs.values():
            if state.out_dir == str(out) and not state.done:
                return state
        self.prune()
        job_id = uuid.uuid4().hex[:8]
        spec = {
            "path": str(p),
            "out_dir": str(out),
            "mode": "export",
            "options": asdict(options),
            "images": images,
            "export": export_params or {},
        }
        queue: Any = mp.get_context("spawn").Queue()
        state = JobState(job_id, str(p), str(out), time.time(), None, queue)
        self.jobs[job_id] = state
        threading.Thread(target=self._run, args=(state, spec, queue), daemon=True).start()
        return state

    @staticmethod
    def _run(state: JobState, spec: dict[str, Any], queue: Any) -> None:
        """Wait for a free analysis slot, run the worker process, then trim the cache."""

        def waiting() -> None:
            state.last = {
                "type": "progress",
                "stage": "waiting",
                "message": WAIT_MESSAGE,
                "fraction": 0.0,
                "elapsed_s": round(time.time() - state.started, 1),
                "eta_s": None,
            }

        if not RUNNER.acquire(should_stop=lambda: state.cancelled, on_wait=waiting):
            state.error, state.done = "cancelled", True
            return
        try:
            proc = mp.get_context("spawn").Process(
                target=procutil.run_in_group, args=(_worker, spec, queue)
            )
            proc.start()
            state.process = proc  # only once it runs: poll() treats a dead process as a failure
            procutil.register(proc)
            proc.join()
            procutil.unregister(proc)
        finally:
            RUNNER.release()
        cache.evict(cache.max_bytes(), keep=[Path(state.out_dir)])

    def poll(self, job_id: str) -> JobState:
        """Drain progress messages and update the job's state."""
        state = self.jobs.get(job_id)
        if state is None:
            raise ValueError(f"unknown job '{job_id}'")
        self._drain(state)
        if not state.done and state.process is not None and not state.process.is_alive():
            self._drain(state)  # a message can arrive between the first drain and the exit
            if not state.done:
                state.error, state.done = "the analysis process stopped unexpectedly", True
        return state

    @staticmethod
    def _drain(state: JobState) -> None:
        while state.queue is not None and not state.queue.empty():
            msg = state.queue.get()
            if msg["type"] == "progress":
                state.last = msg
            elif msg["type"] == "done":
                state.summary, state.done = msg["summary"], True
                if msg["summary"]["status"] != "ok":
                    state.error = "; ".join(str(e) for e in msg["summary"]["errors"]) or "failed"
            else:
                state.error, state.done = msg["message"], True


MANAGER = JobManager()
