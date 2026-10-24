# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""One result cache for the CLI export, the MCP server and the web UI.

An entry is a folder named after a hash of the STEP file's bytes and the options that change the
result (:func:`cache_key`), so the same file analysed from any front end lands in the same place.
The cache lives in a per-user, private directory; it is trimmed least-recently-used first
(:func:`evict`) and an entry is only trusted after :func:`load_report` has checked it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stepscribe import __version__

if TYPE_CHECKING:
    from stepscribe.analysis import AnalyzeOptions
    from stepscribe.models.schema import Report

STAMP = ".stepscribe_export.json"
CHUNK = 1 << 20
DEFAULT_MAX_GB = 2.0


def max_bytes() -> int:
    """Size the cache is trimmed to after a job (``--cache-max-gb`` / STEPSCRIBE_CACHE_MAX_GB)."""
    try:
        gb = float(os.environ.get("STEPSCRIBE_CACHE_MAX_GB", DEFAULT_MAX_GB))
    except ValueError:
        gb = DEFAULT_MAX_GB
    return int(max(gb, 0.0) * 1024**3)


def set_max_gb(gb: float) -> None:
    os.environ["STEPSCRIBE_CACHE_MAX_GB"] = str(gb)


# ------------------------------------------------------------------ location
_fallbacks: dict[str, Path] = {}
_last_reason: str | None = None


def default_root(platform: str, env: Mapping[str, str], home: Path) -> Path:
    """The per-user cache folder for an OS (``STEPSCRIBE_CACHE`` is handled by the caller)."""
    if platform == "win32":
        base = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return base / "stepscribe" / "Cache"
    if platform == "darwin":
        return home / "Library" / "Caches" / "stepscribe"
    return Path(env.get("XDG_CACHE_HOME") or home / ".cache") / "stepscribe"


def unsafe_reason(path: Path) -> str | None:
    """Why *path* must not be used as the cache (a link, or not ours), else None."""
    if path.is_symlink():
        return "is a symbolic link"
    if hasattr(os, "getuid"):
        st = path.lstat()
        if st.st_uid != os.getuid():
            return "owned by another user"
        if st.st_mode & 0o022:
            return "writable by other users"
    return None


def fallback_reason() -> str | None:
    """Why the last :func:`cache_root` call used a temporary folder instead, or None."""
    return _last_reason


def cache_root() -> Path:
    """The cache folder, created private (0o700). Falls back to a fresh temp folder if unsafe."""
    global _last_reason
    env = os.environ.get("STEPSCRIBE_CACHE")
    root = Path(env) if env else default_root(sys.platform, os.environ, Path.home())
    reason: str | None = None
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        reason = unsafe_reason(root)
        if reason is None and hasattr(os, "getuid"):
            root.chmod(0o700)
    except OSError as exc:
        reason = f"cannot be created ({exc.__class__.__name__})"
    _last_reason = reason
    if reason is None:
        return root
    key = str(root)
    if key not in _fallbacks or not _fallbacks[key].is_dir():
        _fallbacks[key] = Path(tempfile.mkdtemp(prefix="stepscribe_cache_"))
    return _fallbacks[key]


# ----------------------------------------------------------------------- key
_digests: dict[tuple[str, int, int], str] = {}


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def file_digest(path: str | Path) -> str:
    """sha256 of a file, read in 1 MB chunks and remembered per (path, size, mtime)."""
    p = Path(path)
    st = p.stat()
    memo = (str(p.resolve()), st.st_size, st.st_mtime_ns)
    if memo not in _digests:
        _digests[memo] = _hash_file(p)
    return _digests[memo]


def cache_key(
    path: str | Path | Sequence[str | Path],
    options: AnalyzeOptions,
    context: str | Path | None = None,
) -> str:
    """sha256 over the file's bytes, the options that change results, the context file and versions.

    Several files hash their sorted digests, so the order they are given in does not matter; the
    context file carries any designer offsets, so a changed offset changes the key.
    """
    from stepscribe.models.schema import SCHEMA_VERSION

    h = hashlib.sha256()
    files = [path] if isinstance(path, (str, Path)) else list(path)
    if len(files) == 1:
        h.update(file_digest(files[0]).encode())
    else:
        h.update(b"files:" + "|".join(sorted(file_digest(p) for p in files)).encode())
    h.update(json.dumps(asdict(options), sort_keys=True, default=str).encode())
    if context:
        h.update(file_digest(context).encode())
    h.update(f"{__version__}|{SCHEMA_VERSION}".encode())
    return h.hexdigest()


def entry_dir(path: str | Path, options: AnalyzeOptions, context: str | Path | None = None) -> Path:
    """The cache folder for one file and one set of options."""
    return cache_root() / cache_key(path, options, context)[:16]


# ------------------------------------------------------------ trust and reuse
def _entries(root: Path) -> list[Path]:
    return [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]


def _size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file() and not f.is_symlink())


def touch(entry: Path) -> None:
    """Mark an entry as just used, so eviction keeps it."""
    try:
        os.utime(entry, None)
    except OSError:
        pass


def export_folder(
    path: str | Path, options: AnalyzeOptions, context: str | Path | None = None
) -> Path | None:
    """The finished, validated export folder for these inputs, or None (recompute)."""
    from stepscribe.models.schema import SCHEMA_VERSION

    entry = entry_dir(path, options, context)
    if not entry.is_dir():
        return None
    for folder in sorted(entry.glob("*_stepscribe")):
        try:
            stamp: dict[str, Any] = json.loads((folder / STAMP).read_text(encoding="utf-8"))
            if (
                stamp.get("file_sha256") != file_digest(path)
                or stamp.get("tool_version") != __version__
                or stamp.get("schema_version") != SCHEMA_VERSION
                or not isinstance(stamp.get("key"), str)
            ):
                continue
            files = stamp["result"]["files"]
            if not (folder / "data" / "report.json").is_file() or not all(
                (folder / f["path"]).exists() for f in files
            ):
                continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        touch(entry)
        return folder
    return None


def load_report(
    path: str | Path, options: AnalyzeOptions, context: str | Path | None = None
) -> Report | None:
    """The cached report for these inputs, or None if there is none or it cannot be trusted."""
    from pydantic import ValidationError

    from stepscribe.models.schema import SCHEMA_VERSION, Report

    folder = export_folder(path, options, context)
    if folder is None:
        return None
    try:
        report = Report.model_validate_json((folder / "data" / "report.json").read_bytes())
    except (OSError, ValueError, ValidationError):
        return None
    return report if report.meta.schema_version == SCHEMA_VERSION else None


# ------------------------------------------------------------------ eviction
def evict(max_bytes: int, keep: Iterable[Path] = ()) -> list[Path]:
    """Delete least-recently-used entries until the cache fits in *max_bytes*.

    Entries in *keep* (the one just written) are never deleted. Returns what was removed.
    """
    root = cache_root()
    protected = {Path(k).resolve() for k in keep}
    entries = sorted(_entries(root), key=lambda p: p.stat().st_mtime)
    sizes = {p: _size(p) for p in entries}
    total = sum(sizes.values())
    removed: list[Path] = []
    for p in entries:
        if total <= max_bytes:
            break
        if p.resolve() in protected:
            continue
        shutil.rmtree(p, ignore_errors=True)
        total -= sizes[p]
        removed.append(p)
    return removed


def info() -> dict[str, Any]:
    """Where the cache is and how big."""
    root = cache_root()
    entries = _entries(root)
    return {
        "path": str(root),
        "entries": len(entries),
        "bytes": sum(_size(p) for p in entries),
        "fallback_reason": fallback_reason(),
    }


def clear() -> int:
    """Delete every entry; returns how many."""
    root = cache_root()
    entries = _entries(root)
    for p in entries:
        shutil.rmtree(p, ignore_errors=True)
    return len(entries)
