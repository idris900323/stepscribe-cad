"""Problems found by running a real design (a robot chassis assembly) through the pack: one test each."""

from __future__ import annotations

from pathlib import Path

import pytest

from stepscribe.geometry.properties import guess_density
from stepscribe.pack.writer import write_pack
from stepscribe.ui.server import BadRequest, _params


# 1 -------------------------------------------------------- material from a name
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("bottom plate", None),
        ("front plate", None),
        ("TopPlate", None),
        ("Plate", None),
        ("template", None),
        ("PLA_housing", "pla"),
        ("bracket pla", "pla"),
        ("PLA+ cover", "pla"),
        ("Alu_Bracket", "alu"),
        ("aluminium frame", "alu"),
        ("6061 aluminum", "alu"),
        ("SteelPlate", "steel"),
        ("steel_shaft", "steel"),
        ("petg clip", "petg"),
        ("cfrp tube", None),
        ("CF tube", "cf"),
        ("absolute reference", None),
        ("abs spacer", "abs"),
    ],
)
def test_material_keyword_matches_whole_words_only(name: str, expected: str | None) -> None:
    found = guess_density(name)
    assert (found[1] if found else None) == expected, name


def test_a_part_called_plate_has_no_material_guess(analyses) -> None:  # type: ignore[no-untyped-def]
    part = analyses("two_plates_assembly").report.parts[0]
    assert part.name == "Plate"
    assert part.mass.material_source == "none" and part.mass.material_assumed is None
    assert part.mass.mass_g is None


def test_the_web_page_validates_material_with_the_same_rule() -> None:
    assert _params({"material": "pla"})["material"] == "pla"
    assert _params({"material": "6061 aluminium"})["material"] == "6061 aluminium"
    for bad in ("plate", "template", "unobtainium"):
        with pytest.raises(BadRequest):
            _params({"material": bad})


# 2 ------------------------------------------------------- rotation in degrees once
def test_rotation_angles_are_degrees_in_the_report_and_the_text(
    step_files: dict[str, Path],
    analyses,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    a = analyses("rotated_assembly")
    angles = {
        i.path.rsplit("/", 1)[-1]: i.rotation_axis_angle[1] for i in a.report.assembly.instances
    }
    assert angles["Upright"] == pytest.approx(0.0, abs=1e-6)
    assert angles["QuarterTurn"] == pytest.approx(90.0, abs=1e-4)
    assert angles["ThirdTurn"] == pytest.approx(120.0, abs=1e-4)
    folder = write_pack(a, tmp_path, 60000, None, False)
    text = (folder / "02_assembly.md").read_text(encoding="utf-8")
    assert "rotated 90.0 deg about" in text and "rotated 120.0 deg about" in text
    assert "5156" not in text and "6875" not in text


# 3 --------------------------------------------- the images line follows the files
def test_read_me_says_images_exist_when_the_pack_has_them(
    analyses,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    a = analyses("two_plates_assembly")
    folder = tmp_path / "two_plates_assembly_context_pack"
    (folder / "images").mkdir(parents=True)
    (folder / "images" / "assembly_iso.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # the interview rebuilds the text without rendering again (images=False)
    write_pack(a, tmp_path, 60000, None, False)
    readme = (folder / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
    assert "none were rendered" not in readme
    assert "labels on the images use the same IDs" in readme


def test_read_me_says_no_images_when_there_are_none(
    analyses,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    a = analyses("two_plates_assembly")
    folder = write_pack(a, tmp_path, 60000, None, False)
    assert "none were rendered" in (folder / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")


# 4 -------------------------------------------------- a large thin plate is a plate
def test_a_large_thin_plate_with_holes_is_not_a_shaft(analyses) -> None:  # type: ignore[no-untyped-def]
    part = analyses("large_thin_plate").report.parts[0]
    assert part.shape_class.label == "plate", part.shape_class.evidence
    assert part.shape_class.confidence >= 0.8


def test_real_shafts_and_discs_are_still_revolved_bodies(analyses) -> None:  # type: ignore[no-untyped-def]
    assert analyses("plain_shaft").report.parts[0].shape_class.label == "shaft"
    assert analyses("round_disc").report.parts[0].shape_class.label == "disc"
    assert analyses("tube").report.parts[0].shape_class.label == "tube"
