# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""How long a STEP file will probably take, and when to warn before starting.

Light on purpose (no OCC): the web page and the MCP server call this before they load anything.
"""

from __future__ import annotations

import os

from stepscribe.progress import PRIOR_SECONDS_PER_FACE

FACES_PER_MB = 600  # measured on the robot corpus: about 600 faces per MB of STEP text
ASSEMBLY_FACTOR = 6.0  # parts plus contacts, from progress.ASSEMBLY_PRIOR_FRACTION + 1
MAX_WORKERS = 8
LARGE_BYTES = 50 * 1024**2  # over this, warn
SLOW_SECONDS = 600  # an estimate over this, warn
LINK_MESH_MAX_TRIANGLES = 5000
IMAGE_MAX_SIDE = 1200  # longest side in pixels of the extra images (--image-max-side)  # collision mesh of one robot link (export --meshes)


def parallelism(cpus: int | None = None) -> int:
    """Part-analysis processes a job will use on a machine with *cpus* cores."""
    return max(1, min((cpus or os.cpu_count() or 2) - 1, MAX_WORKERS))


def eta_seconds(size_bytes: float, cpus: int | None = None) -> float:
    """A rough first estimate from the file size; the running job replaces it with a measured one.

    Calibrated against SO_5DOF_ARM100_Assembly.step (7 MB, 8 workers): 215 s measured, 189 s here.
    """
    mb = size_bytes / 1e6
    serial = mb * FACES_PER_MB * PRIOR_SECONDS_PER_FACE * (ASSEMBLY_FACTOR if mb > 0.5 else 1)
    return serial / parallelism(cpus)


def large_file_warning(size_bytes: float, cpus: int | None = None) -> str | None:
    """One sentence for a file that is big or slow, else None."""
    eta = eta_seconds(size_bytes, cpus)
    big = size_bytes > LARGE_BYTES
    if not big and eta <= SLOW_SECONDS:
        return None
    minutes = max(1, round(eta / 60))
    why = f"is {size_bytes / 1024**2:.0f} MB" if big else "is a big assembly"
    return (
        f"This file {why} and will take about {minutes} minute{'s' if minutes != 1 else ''} "
        "and a lot of memory. It will still run; close other heavy programs first."
    )
