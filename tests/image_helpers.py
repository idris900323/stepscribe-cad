"""Shared helpers of the image-set tests."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.pack.writer import write_pack

EXTRA = re.compile(r"_(holes|views|weak|feature|section|contact|link|kin|wall)\w*\.png$")


def fresh(step_files, name: str):  # type: ignore[no-untyped-def]
    """A private analysis: rendering appends to part.images, so cached ones must not be shared."""
    return analyze_full(step_files[name], AnalyzeOptions(no_timestamp=True))


def pack(step_files, root: Path, name: str, image_set: str, **kw) -> Path:  # type: ignore[no-untyped-def]
    return write_pack(
        fresh(step_files, name),
        root / f"{name}_{image_set}",
        images=image_set != "none",
        image_set=image_set,
        **kw,
    )


def extras(folder: Path) -> list[str]:
    """Every extra image of a pack, relative to it."""
    return sorted(
        p.relative_to(folder).as_posix()
        for p in (folder / "images").rglob("*.png")
        if EXTRA.search(p.name)
    )


def non_white(path: Path) -> float:
    arr = np.array(Image.open(path).convert("RGB"))
    return float((arr.sum(axis=2) < 740).mean())


def has_color(path: Path, rgb: tuple[int, int, int], tol: int = 30) -> bool:
    arr = np.array(Image.open(path).convert("RGB")).astype(int)
    return bool((np.abs(arr - np.array(rgb)).max(axis=2) <= tol).sum() > 40)


def index_files(folder: Path) -> list[str]:
    """The file column of images/INDEX.md, as paths relative to the pack."""
    rows = []
    for line in (folder / "images" / "INDEX.md").read_text("utf-8").splitlines():
        cells = line.split("|")
        if len(cells) > 2 and cells[1].strip().endswith(".png"):
            rows.append("images/" + cells[1].strip())
    return sorted(rows)
