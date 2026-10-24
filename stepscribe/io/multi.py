# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Several STEP files as one model: input expansion (folders, zips) and combining.

Each file becomes a top-level node of one assembly.  Every file keeps its own coordinates; a
designer-supplied offset and rotation (``files:`` in ``design_context.yaml``) is the only thing
that moves one.  Names go through ``clean_name`` and the file order never changes the result.
"""

from __future__ import annotations

import hashlib
import math
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from stepscribe.io.discovery import STEP_SUFFIXES, find_step_files
from stepscribe.io.step_reader import (
    InstanceRec,
    ProtoPart,
    SourceRec,
    StepModel,
    StepReadError,
    _is_generic,
    read_step,
)
from stepscribe.text_safety import clean_name

CHUNK = 1 << 20
MAX_ZIP_ENTRIES = 10_000  # entries of any kind: a zip of a million empty files is also a bomb


class InputError(Exception):
    """The files given cannot be used (too many, unsafe zip, not a STEP file)."""


@dataclass(frozen=True)
class InputLimits:
    """What one run may be given."""

    max_files: int = 40
    max_total_bytes: int = 2 * 1024**3
    max_extracted_bytes: int = 2 * 1024**3


# ------------------------------------------------------------------ zip
def _unsafe(name: str) -> bool:
    text = name.replace("\\", "/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return True
    return any(part == ".." for part in PurePosixPath(text).parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16)


def safe_extract_zip(zip_path: Path, dest: Path, limits: InputLimits) -> list[Path]:
    """Extract the ``*.step`` / ``*.stp`` files of a zip into *dest* and return their paths.

    Everything is checked before anything is written: paths that leave the folder, absolute
    paths, drive letters, symbolic links, too many entries, and an unpacked size over the limit
    (the header sizes are checked first and the real bytes are counted while copying).
    """
    name = zip_path.name
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise InputError(f"{name}: not a readable zip file ({exc})") from exc
    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_ENTRIES:
            raise InputError(f"{name}: too many entries in the zip")
        chosen: list[zipfile.ZipInfo] = []
        for info in infos:
            if _unsafe(info.filename):
                raise InputError(f"{name}: unsafe path in the zip: {info.filename!r}")
            if _is_symlink(info):
                raise InputError(f"{name}: the zip contains a symbolic link: {info.filename!r}")
            if PurePosixPath(info.filename.replace("\\", "/")).suffix.lower() in STEP_SUFFIXES:
                chosen.append(info)
        if len(chosen) > limits.max_files:
            raise InputError(f"{name}: at most {limits.max_files} STEP files per run")
        if sum(i.file_size for i in chosen) > limits.max_extracted_bytes:
            raise InputError(f"{name}: the unpacked files are too large")
        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        out: list[Path] = []
        written = 0
        for info in sorted(chosen, key=lambda i: i.filename):
            rel = PurePosixPath(info.filename.replace("\\", "/"))
            target = (root / Path(*rel.parts)).resolve()
            if root not in target.parents:
                raise InputError(f"{name}: unsafe path in the zip: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst:
                while chunk := src.read(CHUNK):
                    written += len(chunk)
                    if written > limits.max_extracted_bytes:
                        raise InputError(f"{name}: the unpacked files are too large")
                    dst.write(chunk)
            out.append(target)
    return out


def expand_inputs(paths: list[Path], limits: InputLimits, workdir: Path) -> list[Path]:
    """STEP files from files, folders (searched recursively) and zips, in the order given."""
    found: list[Path] = []
    seen: set[Path] = set()
    for n, p in enumerate(paths, 1):
        if p.is_dir():
            items = find_step_files(p)
        elif p.suffix.lower() == ".zip":
            items = safe_extract_zip(p, workdir / f"zip{n}", limits)
        elif p.suffix.lower() in STEP_SUFFIXES and p.is_file():
            items = [p]
        else:
            raise InputError(f"{p.name}: not a STEP file, a folder or a zip")
        for item in items:
            key = item.resolve()
            if key not in seen:
                seen.add(key)
                found.append(item)
    if len(found) > limits.max_files:
        raise InputError(f"at most {limits.max_files} STEP files per run (got {len(found)})")
    if sum(f.stat().st_size for f in found) > limits.max_total_bytes:
        raise InputError("the STEP files are too large in total")
    return found


# ------------------------------------------------------------ combining
def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


_USELESS = re.compile(
    r"^(part|solid|shape|body|component|unnamed|untitled|noname|product|nauo)[\s_-]*\d*$",
    re.IGNORECASE,
)


def is_useless_name(name: str | None) -> bool:
    """Empty, generic (``Part``, ``Open CASCADE ...``) or only an id (``Part1``, ``NAUO7``)."""
    return not name or _is_generic(name) or bool(_USELESS.match(name.strip()))


def _has_group(text: str) -> bool:
    from stepscribe.understanding.link_groups import parse_group

    return parse_group(text) is not None


def _name_for(internal: str | None, stem: str, k: int) -> str:
    """The part name: the stem for a useless internal name, else the internal name.

    An internal name with no link or base in it, in a file whose stem has one, gets the stem as a
    prefix so the link is still found.
    """
    raw = clean_name(internal)
    if is_useless_name(raw):
        return stem if k == 1 else f"{stem}_{k}"
    if _has_group(stem) and not _has_group(raw):
        return f"{stem}_{raw}"
    return raw


def _unique(name: str, used: set[str], suffix_sep: str = "_") -> str:
    base, n, cand = name, 1, name
    while cand.lower() in used:
        n += 1
        cand = f"{base}{suffix_sep}{n}"
    used.add(cand.lower())
    return cand


def _matrix(offset: list[float], rotation_deg: list[float]) -> np.ndarray:
    """Rotation about X, then Y, then Z (fixed axes), then the offset, as one 4x4."""
    rx, ry, rz = (math.radians(v) for v in rotation_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = mz @ my @ mx
    m[:3, 3] = offset
    return m


def _vec3(value: Any, what: str) -> list[float]:
    ok = isinstance(value, (list, tuple)) and len(value) == 3
    if not ok or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        raise StepReadError(f"design_context files: {what} must be three numbers")
    return [float(v) for v in value]


def common_name(stems: list[str]) -> str:
    """A name for the combined model: the shared start of the file names, else ``combined``."""
    if not stems:
        return "combined"
    first = stems[0]
    n = 0
    while n < len(first) and all(len(s) > n and s[n].lower() == first[n].lower() for s in stems):
        n += 1
    prefix = first[:n].rstrip(" _-.0123456789")
    return prefix if len(prefix) >= 3 else "combined"


def read_step_files(
    paths: list[Path],
    placements: dict[str, Any] | None = None,
    name: str | None = None,
    limits: InputLimits | None = None,
) -> StepModel:
    """Read several STEP files into one :class:`StepModel` (the files are read one at a time)."""
    limits = limits or InputLimits()
    if len(paths) > limits.max_files:
        raise StepReadError(f"at most {limits.max_files} STEP files per run (got {len(paths)})")
    items = []
    for p in paths:
        if not p.is_file():
            raise StepReadError(f"file not found: {p}")
        items.append((clean_name(p.name) or "model.step", sha256_of(p), p))
    items.sort(key=lambda t: (t[0].lower(), t[1]))
    warnings: list[str] = []
    kept: list[tuple[str, str, Path]] = []
    first_of: dict[str, str] = {}
    for fname, digest, p in items:
        if digest in first_of:
            warnings.append(
                f"{fname} is identical to {first_of[digest]} (same sha256): kept one copy"
            )
            continue
        first_of[digest] = fname
        kept.append((fname, digest, p))
    used_files: set[str] = set()
    named: list[tuple[str, str, Path]] = []
    for fname, digest, p in kept:
        suffix = Path(fname).suffix
        stem = fname[: -len(suffix)] if suffix else fname
        stem = _unique(stem, used_files)  # same cleaned name, different file: link, link_2
        named.append((stem + suffix, digest, p))
    stems_by_file = {f: (f[: -len(Path(f).suffix)] if Path(f).suffix else f) for f, _d, _p in named}

    place = dict(placements or {})
    wanted = {str(k).lower(): v for k, v in place.items()}
    model = StepModel(
        path=", ".join(f for f, _d, _p in named),
        original_unit="mm",
        root_name=name or common_name(list(stems_by_file.values())),
        is_assembly=True,
        warnings=warnings,
    )
    used_protos: set[str] = set()
    used_paths: set[str] = set()
    units: set[str] = set()
    matched: set[str] = set()
    for n, (fname, digest, p) in enumerate(named):
        try:
            part = read_step(p)
        except StepReadError as exc:
            raise StepReadError(f"{fname}: {exc}") from exc
        units.add(part.original_unit)
        stem = stems_by_file[fname]
        spec = wanted.get(fname.lower()) or wanted.get(p.name.lower())
        src = SourceRec(fname, digest, p.stat().st_size)
        shift = np.eye(4)
        if spec is not None:
            matched.add(fname.lower() if fname.lower() in wanted else p.name.lower())
            if not isinstance(spec, dict):
                raise StepReadError(f"design_context files: {fname} must be a mapping")
            src.offset_mm = _vec3(spec.get("offset_mm", [0, 0, 0]), f"{fname} offset_mm")
            src.rotation_deg = _vec3(spec.get("rotation_deg", [0, 0, 0]), f"{fname} rotation_deg")
            src.placement = "designer-supplied"
            shift = _matrix(src.offset_mm, src.rotation_deg)
        model.sources.append(src)
        model.warnings += [f"{fname}: {w}" for w in part.warnings]
        renamed: dict[str, str] = {}
        for k, key in enumerate(sorted(part.protos), 1):
            proto = part.protos[key]
            pname = _unique(_name_for(proto.name, stem, k), used_protos, "_")
            new_key = f"f{n:02d}:{key}"
            renamed[key] = new_key
            model.protos[new_key] = ProtoPart(
                new_key, pname, proto.shape, proto.color_rgb, proto.name_cleaned, fname
            )
        several = len(part.instances) > 1
        for rec in part.instances:
            parts = rec.path.split("/")
            if is_useless_name(parts[-1].rsplit(":", 1)[0]):
                parts[-1] = model.protos[renamed[rec.proto_key]].name
            tail = "/".join(parts)
            path = f"{stem}/{tail}" if several else tail
            path = _unique(path, used_paths, ":")
            parent = f"{stem}/{rec.parent_path}" if rec.parent_path else (stem if several else None)
            sub = rec.subassembly or (stem if several else None)
            model.instances.append(
                InstanceRec(renamed[rec.proto_key], path, shift @ rec.matrix, parent, sub, fname)
            )
    missing = sorted(set(wanted) - matched)
    for key in missing:
        model.warnings.append(f"design_context files: '{key}' matches none of the files")
    if len(units) > 1:
        model.warnings.append(
            f"the files use different length units ({', '.join(sorted(units))}); all are in mm"
        )
    model.original_unit = sorted(units)[0] if len(units) == 1 else "mm"
    return model
