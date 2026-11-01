"""The contact stage reuses the bore faces the part analysis already found.

Finding the concave faces of a part costs one point-in-solid query per cylinder or cone face, which
dominates big parts. The worker that analyses a part used to keep the result to itself, so the
contact stage found them all again on a second copy of the shape.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.assembly import contacts
from stepscribe.features.holes import find_bore_faces
from stepscribe.geometry.part_geom import PartGeom


def test_contacts_start_with_the_bore_faces_already_known(
    step_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    real = contacts.find_bore_faces

    def spy(part: PartGeom):  # type: ignore[no-untyped-def]
        seen.append(part.bores_cache is not None)
        return real(part)

    monkeypatch.setattr(contacts, "find_bore_faces", spy)
    analyze_full(step_files["two_plates_assembly"], AnalyzeOptions(understanding=False))
    assert seen and all(seen)


def test_reused_bore_faces_equal_a_fresh_computation(step_files: dict[str, Path]) -> None:
    analysis = analyze_full(step_files["two_plates_assembly"], AnalyzeOptions(understanding=False))
    for ap in analysis.parts:
        reused = ap.geom.bores_cache
        assert reused is not None and reused
        fresh = find_bore_faces(PartGeom(ap.geom.name, ap.geom.shape))
        assert len(reused) == len(fresh)
        for r, f in zip(reused, fresh, strict=True):
            assert (r.idx, r.kind) == (f.idx, f.kind)
            for name in ("origin", "direction"):
                np.testing.assert_allclose(getattr(r, name), getattr(f, name), atol=1e-9)
            for name in ("span_deg", "v0", "v1", "radius_ref", "semi_angle"):
                assert getattr(r, name) == pytest.approx(getattr(f, name), abs=1e-9)
