# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""At most N heavy analyses at a time in this process (the web UI and the MCP server share it).

Every analysis starts its own pool of part workers, so running several at once can use several
times the RAM of one. Extra jobs wait here and say so in their progress.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

WAIT_MESSAGE = "waiting for another analysis to finish"


class Runner:
    """A counting gate with a cancellable wait."""

    def __init__(self, max_jobs: int = 1) -> None:
        self._cond = threading.Condition()
        self._max = max(1, max_jobs)
        self._running = 0

    @property
    def max_jobs(self) -> int:
        return self._max

    @property
    def running(self) -> int:
        return self._running

    def set_max_jobs(self, n: int) -> None:
        with self._cond:
            self._max = max(1, n)
            self._cond.notify_all()

    def acquire(
        self,
        should_stop: Callable[[], bool] | None = None,
        on_wait: Callable[[], None] | None = None,
    ) -> bool:
        """Wait for a free slot. False if *should_stop* turned true first (the job was cancelled)."""
        told = False
        with self._cond:
            while self._running >= self._max:
                if should_stop is not None and should_stop():
                    return False
                if not told and on_wait is not None:
                    told = True
                    on_wait()
                self._cond.wait(0.1)
            if should_stop is not None and should_stop():
                return False
            self._running += 1
            return True

    def release(self) -> None:
        with self._cond:
            self._running = max(0, self._running - 1)
            self._cond.notify_all()

    @contextmanager
    def slot(self, on_wait: Callable[[], None] | None = None) -> Iterator[None]:
        self.acquire(on_wait=on_wait)
        try:
            yield
        finally:
            self.release()


def _default_max() -> int:
    env = os.environ.get("STEPSCRIBE_MAX_JOBS", "")
    return int(env) if env.isdigit() and int(env) > 0 else 1


RUNNER = Runner(_default_max())
