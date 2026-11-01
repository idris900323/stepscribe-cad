"""Image type 6 (standard, assemblies): the contact map."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from image_helpers import extras, fresh, non_white, pack
from PIL import Image

from stepscribe.describe.image_captions import MAX_CONTACTS, selected_contacts
from stepscribe.render.contact_view import contact_anchor


def test_an_assembly_gets_a_contact_map_and_a_single_part_a_note(
    step_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    asm = pack(step_files, tmp_path, "two_plates_assembly", "standard")
    path = asm / "images" / "contact_map.png"
    assert path.is_file() and 0.02 < non_white(path) < 0.98 and max(Image.open(path).size) <= 1200
    assert "images/contact_map.png" in (asm / "01_overview.md").read_text("utf-8")
    index = (asm / "images" / "INDEX.md").read_text("utf-8")
    assert "| contact_map.png |" in index and "C001" in index
    single = pack(step_files, tmp_path, "plate_4xM3", "standard")
    assert not (single / "images" / "contact_map.png").exists()
    assert "contact map: not drawn, a single part has no contacts" in (
        single / "images" / "INDEX.md"
    ).read_text("utf-8")
    assert "images/contact_map.png" not in extras(asm)  # the per-part list is separate


def test_the_basic_set_has_no_contact_map(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert not (
        pack(step_files, tmp_path, "two_plates_assembly", "basic") / "images" / "contact_map.png"
    ).exists()


def test_the_selection_is_faces_and_fits_largest_first_and_capped(step_files) -> None:  # type: ignore[no-untyped-def]
    report = fresh(step_files, "two_plates_assembly").report
    chosen = selected_contacts(report)
    assert chosen and len(chosen) <= MAX_CONTACTS
    assert all(c.kind in ("planar_face", "cylindrical_fit") for c in chosen)
    areas = [c.contact_area_mm2 or 0.0 for c in chosen]
    assert areas == sorted(areas, reverse=True)


def test_the_label_sits_inside_the_overlap_of_the_two_boxes() -> None:
    a_lo, a_hi = np.array([0.0, 0, 0]), np.array([10.0, 10, 5])
    b_lo, b_hi = np.array([0.0, 0, 5]), np.array([10.0, 10, 10])  # stacked: they only touch
    p = contact_anchor(a_lo, a_hi, b_lo, b_hi)
    assert np.allclose(p, [5, 5, 5])
    assert np.all(p >= np.maximum(a_lo, b_lo)) and np.all(p <= np.minimum(a_hi, b_hi))
    far = contact_anchor(a_lo, a_hi, b_lo + 100, b_hi + 100)  # no overlap: between the centres
    assert np.allclose(far, 0.25 * (a_lo + a_hi + b_lo + 100 + b_hi + 100))


def test_the_caption_and_the_markdown_list_the_contacts(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    folder = pack(step_files, tmp_path, "two_plates_assembly", "standard")
    index = (folder / "images" / "INDEX.md").read_text("utf-8")
    line = next(x for x in index.splitlines() if "contact_map.png" in x)
    assert "planar_face" in line and "mm2" in line and "INS001 - INS002" in line
    overview = (folder / "01_overview.md").read_text("utf-8")
    assert next(x for x in overview.splitlines() if "contact_map.png" in x).startswith(
        "- images/contact_map.png: The assembly with the parts"
    )
