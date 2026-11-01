"""Image type 4 (full set): the feature highlight."""

from __future__ import annotations

from pathlib import Path

from image_helpers import extras, has_color, non_white, pack

from stepscribe.render.feature_view import FILLET, HOLE, OPENING


def test_only_the_full_set_has_the_feature_highlight(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    standard = pack(step_files, tmp_path, "slot_and_fillets", "standard")
    full = pack(step_files, tmp_path, "slot_and_fillets", "full")
    assert "images/parts/PRT001_features.png" not in extras(standard)
    assert "images/parts/PRT001_features.png" in extras(full)
    assert set(extras(standard)) <= set(extras(full))


def test_the_colours_of_the_families_are_on_the_image(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = pack(step_files, tmp_path, "slot_and_fillets", "full")
    path = folder / "images/parts/PRT001_features.png"
    assert 0.02 < non_white(path) < 0.98
    assert has_color(path, OPENING) or has_color(path, FILLET) or has_color(path, HOLE)
    text = (folder / "images" / "INDEX.md").read_text("utf-8")
    assert "feature highlight" in text and "PRT001_features.png" in text


def test_the_caption_lists_the_feature_ids(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = pack(step_files, tmp_path, "slot_and_fillets", "full")
    index = (folder / "images" / "INDEX.md").read_text("utf-8")
    line = next(x for x in index.splitlines() if "PRT001_features.png" in x)
    assert "isometric view with its features marked" in line
    for family_id in ("C001", "FL001"):
        assert family_id in line, family_id


def test_a_part_with_no_features_is_skipped_with_a_note(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = pack(step_files, tmp_path, "cube_10", "full")
    assert "images/parts/PRT001_features.png" not in extras(folder)
    index = (folder / "images" / "INDEX.md").read_text("utf-8")
    assert "feature highlight: not drawn for 1 part without features (PRT001)" in index
