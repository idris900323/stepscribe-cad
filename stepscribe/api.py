# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Public Python API: analyse STEP files and build context packs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS_Shape

from stepscribe import __version__, config, timings
from stepscribe.analysis import (
    AnalyzedPart,
    AnalyzeOptions,
    analyze_brep_file,
    assign_part_ids,
    bore_chunk,
    may_split_bores,
    split_bodies,
    worker_choice,
)
from stepscribe.features.holes import assemble_bores
from stepscribe.geometry.occ_utils import unique_subshapes
from stepscribe.geometry.part_geom import PartGeom
from stepscribe.io.step_apply import step_data
from stepscribe.io.step_reader import StepModel, StepReadError, read_step
from stepscribe.models.schema import SCHEMA_VERSION, Meta, Part, Report
from stepscribe.progress import Tracker

PARALLEL_MIN_PARTS = 3
PARALLEL_MIN_FACES = 300  # below this, starting processes costs more than it saves
HEAVY_BORE_FACES = (
    300  # a part with this many faces has its hole-detection ray casts split over the pool
)
MIN_CHUNK_FACES = 40  # faces per ray-cast task, at least


@dataclass
class Analysis:
    """A report together with the live geometry behind it."""

    report: Report
    model: StepModel | None
    parts: list[AnalyzedPart] = field(default_factory=list)
    proto_to_parts: dict[str, list[str]] = field(default_factory=dict)  # proto key -> part ids
    understanding_pipeline: Any = None  # cached stages, reused when answers change


def _tolerances() -> dict[str, float]:
    return {
        k: float(v)
        for k, v in sorted(vars(config).items())
        if k.isupper() and isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def _meta(files: list[str], unit: str, opts: AnalyzeOptions) -> Meta:
    return Meta(
        schema_version=SCHEMA_VERSION,
        tool_version=__version__,
        generated_at=None if opts.no_timestamp else datetime.now(UTC).isoformat(timespec="seconds"),
        source_files=files,
        original_length_unit=unit,
        tolerances=_tolerances(),
        options={
            "density": opts.density,
            "material": opts.material,
            "up": opts.up,
            "front": opts.front,
            "check_interference": opts.check_interference,
            "understanding": opts.understanding,
            "check_motion": opts.check_motion,
            "debug_graphs": opts.debug_graphs,
            **({"debug_kinematics": True} if opts.debug_kinematics else {}),
        },
    )


def _analyse_bodies(
    bodies: list[tuple[str, str, TopoDS_Shape, list[float] | None]],
    faces: dict[int, int],
    source_file: str,
    opts: AnalyzeOptions,
    tracker: Tracker,
    errors: list[dict[str, object]],
) -> list[tuple[str, PartGeom, Part]]:
    """Analyse every body, on a process pool for large assemblies.

    Serial and parallel runs both analyse each part from a BREP copy, so the report is the same
    whatever the worker count (a reload shifts floats by ~1e-13, which can flip ties such as the
    axes of a square box, so mixing live and reloaded shapes would not be reproducible).
    """
    import multiprocessing as mp
    import tempfile
    from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
    from concurrent.futures.process import BrokenProcessPool

    from OCP.BRepTools import BRepTools

    choice = worker_choice(len(bodies), max(faces.values(), default=0))
    workers = choice.workers
    text = choice.describe()
    if len(bodies) < PARALLEL_MIN_PARTS or sum(faces.values()) < PARALLEL_MIN_FACES:
        workers = 1
        text = (
            f"part workers: 1 (small model: fewer than {PARALLEL_MIN_PARTS} parts or {PARALLEL_MIN_FACES} faces); "
            + text
        )
    timings.note("part_workers", text)
    timings.count("part_workers", workers)
    tracker.emit(text)
    results: dict[int, Part] = {}
    bores: dict[int, list[Any] | None] = {}

    def failed(i: int, exc: Exception) -> None:
        name = bodies[i][1]
        errors.append({"file": source_file, "part": name, "error": f"{type(exc).__name__}: {exc}"})
        tracker.part_done(name, faces[id(bodies[i][2])], 0.0)

    with tempfile.TemporaryDirectory(prefix="stepscribe_") as tmp:
        paths: list[str] = []
        for i, (_k, name, shape, _c) in enumerate(bodies):
            f = str(Path(tmp) / f"b{i}.brep")
            if not BRepTools.Write_s(shape, f):
                raise RuntimeError(f"could not serialise part '{name}'")
            paths.append(f)

        def args(i: int) -> tuple[str, str, str, AnalyzeOptions, list[float] | None]:
            return paths[i], bodies[i][1], source_file, opts, bodies[i][3]

        def n_faces(i: int) -> int:
            return faces[id(bodies[i][2])]

        if workers == 1:
            for i in range(len(bodies)):
                try:
                    results[i], secs, bores[i] = analyze_brep_file(*args(i))
                except Exception as exc:  # noqa: BLE001
                    failed(i, exc)
                    continue
                timings.add_part(bodies[i][1], faces[id(bodies[i][2])], secs)
                tracker.part_done(bodies[i][1], faces[id(bodies[i][2])], secs)
        else:
            order = sorted(range(len(bodies)), key=lambda i: -faces[id(bodies[i][2])])  # big first
            tracker.stage("parts", f"analysing {len(bodies)} parts on {workers} processes")
            retry: list[int] = []
            split = may_split_bores(workers, max(faces.values(), default=0))  # memory rule
            try:
                with ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn")) as pool:
                    pending: dict[Future[Any], tuple[str, int]] = {}
                    chunks: dict[int, list[Future[Any]]] = {}
                    left: dict[int, int] = {}
                    # The ray casts of hole detection are independent per face. For a big part they
                    # go to the pool first, in chunks, so the whole pool works on the part that
                    # would otherwise be the slowest; its analysis then starts with the bores found.
                    for i in (i for i in order if split and n_faces(i) >= HEAVY_BORE_FACES):
                        total = n_faces(i)
                        step = max(MIN_CHUNK_FACES, -(-total // (workers * 3)))
                        futs = [
                            pool.submit(
                                bore_chunk, paths[i], bodies[i][1], lo, min(lo + step, total)
                            )
                            for lo in range(0, total, step)
                        ]
                        chunks[i], left[i] = futs, len(futs)
                        pending.update({f: ("chunk", i) for f in futs})
                        timings.count("bore_chunks", len(futs))
                        tracker.stage(
                            "parts",
                            f"hole detection of {bodies[i][1]} split into {len(futs)} tasks",
                        )
                    for i in order:
                        if i not in chunks:
                            pending[pool.submit(analyze_brep_file, *args(i))] = ("part", i)
                    while pending:
                        done, _not_done = wait(pending, return_when=FIRST_COMPLETED)
                        for fut in done:
                            kind, i = pending.pop(fut)
                            if kind == "chunk":
                                left[i] -= 1
                                if left[i] == 0:
                                    try:
                                        found = assemble_bores(
                                            r for f in chunks[i] for r in f.result()
                                        )
                                    except BrokenProcessPool:
                                        raise
                                    except Exception:  # noqa: BLE001
                                        found = None  # the part's own worker finds its bores
                                    pending[pool.submit(analyze_brep_file, *args(i), found)] = (
                                        "part",
                                        i,
                                    )
                                continue
                            try:
                                part, secs, bores_found = fut.result()
                            except BrokenProcessPool:
                                retry.append(i)  # e.g. the caller is a script without a main guard
                                continue
                            except Exception as exc:  # noqa: BLE001
                                failed(i, exc)
                                continue
                            results[i] = part
                            bores[i] = bores_found
                            timings.add_part(bodies[i][1], n_faces(i), secs)
                            # wall-clock share, so the ETA (faces per second) reflects the parallel speed
                            tracker.part_done(bodies[i][1], n_faces(i), secs / workers)
            except (BrokenProcessPool, RuntimeError, OSError):
                retry = [i for i in order if i not in results]
            if retry:
                tracker.stage(
                    "parts",
                    f"process pool unavailable: analysing {len(retry)} part(s) in this process",
                )
            for i in sorted(retry):
                if i in results:
                    continue
                try:
                    results[i], secs, bores[i] = analyze_brep_file(*args(i))
                except Exception as exc:  # noqa: BLE001
                    failed(i, exc)
                    continue
                timings.add_part(bodies[i][1], faces[id(bodies[i][2])], secs)
                tracker.part_done(bodies[i][1], faces[id(bodies[i][2])], secs)
    out = []
    for i in sorted(results):
        geom = PartGeom(bodies[i][1], bodies[i][2])
        geom.bores_cache = bores.get(i)  # already found by the part analysis
        out.append((bodies[i][0], geom, results[i]))
    return out


def analyze_full(
    path: str | Path, options: AnalyzeOptions | None = None, tracker: Tracker | None = None
) -> Analysis:
    """Analyse one STEP file; unreadable files yield a report with an ``errors`` entry."""
    from stepscribe import envcheck

    envcheck.check_occt()  # a clear one-liner instead of a crash deep inside OCCT calls
    opts = options or AnalyzeOptions()
    p = Path(path)
    try:
        with timings.stage("load"):
            model = read_step(p)
    except StepReadError as exc:
        report = Report(
            meta=_meta([p.name], "mm", opts), parts=[], errors=[{"file": p.name, "error": str(exc)}]
        )
        return Analysis(report, None)

    tracker = tracker or Tracker()
    bodies = [
        (key, name, shape, model.protos[key].color_rgb)
        for key in sorted(model.protos)
        for name, shape in split_bodies(model.protos[key].name, model.protos[key].shape)
    ]
    faces = {id(shape): len(unique_subshapes(shape, TopAbs_FACE)) for _k, _n, shape, _c in bodies}
    tracker.plan_parts(
        len(bodies),
        sum(faces.values()),
        model.is_assembly or len(model.instances) > 1 or len(bodies) > 1,
    )
    parts: list[AnalyzedPart] = []
    proto_parts: dict[str, list[AnalyzedPart]] = {}
    warnings = list(model.warnings)
    errors: list[dict[str, object]] = []
    with timings.stage("parts"):
        done_parts = _analyse_bodies(bodies, faces, p.name, opts, tracker, errors)
    for key, geom, part in done_parts:
        part.name_cleaned = model.protos[key].name_cleaned
        proto = model.protos[key]
        part.from_step = step_data(
            part,
            geom,
            proto.product_name,
            proto.meta,
            [d for d in model.dimensions if d.owner_key == key],
            model.original_unit,
            opts,
        )
        ap = AnalyzedPart(part, geom)
        parts.append(ap)
        proto_parts.setdefault(key, []).append(ap)
    assign_part_ids([ap.part for ap in parts])
    parts.sort(key=lambda ap: ap.part.id)
    report = Report(
        meta=_meta([p.name], model.original_unit, opts),
        parts=[ap.part for ap in parts],
        warnings=warnings,
        errors=errors,
    )
    analysis = Analysis(
        report, model, parts, {k: [ap.part.id for ap in v] for k, v in proto_parts.items()}
    )
    from stepscribe.assembly import build_assembly

    tracker.stage("assembly", "building assembly relationships")
    with timings.stage("assembly"):
        report.assembly = build_assembly(analysis, opts, tracker)
    if opts.understanding:
        from stepscribe.understanding import build_understanding

        try:
            with timings.stage("understanding"):
                report.understanding = build_understanding(analysis, opts, tracker)
        except Exception as exc:  # noqa: BLE001 - the measured report must survive
            report.warnings.append(f"understanding layer failed: {type(exc).__name__}: {exc}")
    return analysis


def restore_analysis(
    path: str | Path, options: AnalyzeOptions, report_json: str | Path
) -> Analysis:
    """An :class:`Analysis` for the interview, from a saved ``report.json`` and the STEP file.

    Reads the STEP file again (fast) and takes every measured result from the report, so the
    expensive part analysis and the assembly analysis are not repeated; only the understanding
    pipeline is built again, when the session asks for it.
    """
    report = Report.model_validate_json(Path(report_json).read_bytes())
    model = read_step(path)
    by_name: dict[str, list[Part]] = {}
    for part in report.parts:
        by_name.setdefault(part.name, []).append(part)
    parts: list[AnalyzedPart] = []
    proto_parts: dict[str, list[AnalyzedPart]] = {}
    for key in sorted(model.protos):
        for name, shape in split_bodies(model.protos[key].name, model.protos[key].shape):
            if not by_name.get(name):
                raise ValueError("the saved report does not match the STEP file")
            ap = AnalyzedPart(by_name[name].pop(0), PartGeom(name, shape))
            parts.append(ap)
            proto_parts.setdefault(key, []).append(ap)
    parts.sort(key=lambda ap: ap.part.id)
    return Analysis(
        report, model, parts, {k: [ap.part.id for ap in v] for k, v in proto_parts.items()}
    )


def analyze(path: str | Path, options: AnalyzeOptions | None = None) -> Report:
    """Analyse a STEP file and return its :class:`Report`."""
    return analyze_full(path, options).report


def build_context_pack(
    path: str | Path,
    out_dir: str | Path,
    options: AnalyzeOptions | None = None,
    budget_tokens: int = config.DEFAULT_BUDGET_TOKENS,
    context_file: str | Path | None = None,
    images: bool = False,
    tracker: Tracker | None = None,
) -> Path:
    """Analyse *path* and write ``<name>_context_pack/`` under *out_dir*; returns its folder."""
    from stepscribe.pack.design_context import apply_context, load_context
    from stepscribe.pack.writer import write_pack

    opts = options or AnalyzeOptions()
    if context_file:
        ctx = load_context(context_file)
        apply_context(opts, ctx)
    tracker = tracker or Tracker()
    tracker.images_wanted = images
    analysis = analyze_full(path, opts, tracker)
    folder = write_pack(analysis, Path(out_dir), budget_tokens, context_file, images, tracker)
    tracker.finish("pack written")
    return folder
