# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Opt-in stage timings: ``stepscribe export --timings`` writes ``data/timings.json``.

Off by default (``STEPSCRIBE_TIMINGS`` unset): every call is then a flag check and returns at once,
so analysis results and cost are unchanged. Nested stages use dotted names (``assembly.contacts``
runs inside ``assembly``), so their times overlap and must not be added up.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from typing import Any

ENV = "STEPSCRIBE_TIMINGS"
_stages: dict[str, float] = {}
_parts: list[dict[str, Any]] = []
_counts: dict[str, float] = {}
_notes: dict[str, str] = {}
_started = [0.0]


def enabled() -> bool:
    return os.environ.get(ENV) == "1"


def enable() -> None:
    os.environ[ENV] = "1"


def reset() -> None:
    _stages.clear()
    _parts.clear()
    _counts.clear()
    _notes.clear()
    _started[0] = time.perf_counter()


@contextmanager
def _timed(name: str) -> Iterator[None]:
    t0 = time.perf_counter()
    try:
        yield
    finally:
        _stages[name] = _stages.get(name, 0.0) + time.perf_counter() - t0


def stage(name: str) -> AbstractContextManager[None]:
    """Time a block under *name* (repeated blocks add up)."""
    return _timed(name) if enabled() else nullcontext()


def add_part(name: str, faces: int, seconds: float) -> None:
    if enabled():
        _parts.append({"part": name, "faces": faces, "seconds": round(seconds, 3)})


def count(name: str, value: float = 1) -> None:
    if enabled():
        _counts[name] = _counts.get(name, 0) + value


def note(name: str, text: str) -> None:
    """A text fact of the run (for example the part-worker pool and the rule that chose it)."""
    if enabled():
        _notes[name] = text


def snapshot() -> dict[str, Any]:
    return {
        "stages_s": dict(_stages),
        "parts": list(_parts),
        "counts": dict(_counts),
        "notes": dict(_notes),
    }


def write(path: Path) -> None:
    """Write the collected times (rounded) next to the report."""
    data = snapshot()
    data["stages_s"] = {k: round(v, 3) for k, v in sorted(data["stages_s"].items())}
    data["total_s"] = round(time.perf_counter() - _started[0], 3)
    data["note"] = (
        "stage times overlap when nested (dotted names); part seconds are wall time in a worker"
    )
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
