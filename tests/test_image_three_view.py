"""Image type 2, the three-view drawing."""

from __future__ import annotations

from pathlib import Path

import pytest
from image_helpers import fresh, non_white, pack
from PIL import Image

from stepscribe.pack.writer import write_pack


def test_a_part_gets_one_sheet_with_the_overall_size(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = pack(step_files, tmp_path, "plate_4xM3", "standard")
    path = folder / "images/parts/PRT001_views.png"
    assert 0.02 < non_white(path) < 0.95 and max(Image.open(path).size) <= 1200
    text = (folder / "images" / "INDEX.md").read_text("utf-8")
    assert "three orthographic views (front, top, right)" in text
    assert "Oriented bounding box 60.0 x 60.0 x 5.0 mm" in text


def test_a_failing_view_is_a_note_and_the_other_images_remain(
    step_files, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    import stepscribe.render.three_view as tv

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(tv, "make", boom)
    folder = write_pack(
        fresh(step_files, "plate_4xM3"), tmp_path, images=True, image_set="standard"
    )
    assert (folder / "images/parts/PRT001_holes.png").is_file()
    assert not (folder / "images/parts/PRT001_views.png").exists()
    index = (folder / "images" / "INDEX.md").read_text("utf-8")
    assert "three-view drawing PRT001: not drawn (RuntimeError)" in index
