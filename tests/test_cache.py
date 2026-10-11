"""H3: one result cache for the CLI export, the MCP server and the web UI."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from stepscribe import cache, exporter, jobs
from stepscribe.analysis import AnalyzeOptions

OPTS = AnalyzeOptions(no_timestamp=True)


def _file(tmp_path: Path, content: bytes = b"ISO-10303-21;\nDATA;\n", name: str = "a.step") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


# ------------------------------------------------------------------ location
@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        (
            "win32",
            {"LOCALAPPDATA": "C:/Users/me/AppData/Local"},
            "C:/Users/me/AppData/Local/stepscribe/Cache",
        ),
        ("darwin", {}, "/home/me/Library/Caches/stepscribe"),
        ("linux", {"XDG_CACHE_HOME": "/xdg"}, "/xdg/stepscribe"),
        ("linux", {}, "/home/me/.cache/stepscribe"),
    ],
)
def test_default_cache_location_per_os(platform: str, env: dict[str, str], expected: str) -> None:
    got = cache.default_root(platform, env, Path("/home/me"))
    assert got.as_posix() == expected


def test_environment_variable_overrides_the_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "custom"))
    assert cache.cache_root() == tmp_path / "custom"
    assert (tmp_path / "custom").is_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_cache_directory_is_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "c"))
    assert (cache.cache_root().stat().st_mode & 0o777) == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="needs symlinks")
def test_a_symlinked_cache_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(link))
    root = cache.cache_root()
    assert root.resolve() != target.resolve() and not root.is_symlink()


def test_an_unsafe_cache_directory_falls_back_to_a_fresh_temp_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Also covers the 'not owned by this user' case on every OS (the check is injectable)."""
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "shared"))
    (tmp_path / "shared").mkdir()
    monkeypatch.setattr(cache, "unsafe_reason", lambda p: "owned by another user")
    root = cache.cache_root()
    assert root != tmp_path / "shared" and root.is_dir()
    assert cache.fallback_reason() == "owned by another user"


# ---------------------------------------------------------------------- key
def test_file_digest_is_sha256_and_streams_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = os.urandom(3 * 1024 * 1024 + 17)
    p = _file(tmp_path, data)

    def boom(self: Path) -> bytes:
        raise AssertionError("the whole file must not be read into memory")

    monkeypatch.setattr(Path, "read_bytes", boom)
    assert cache.file_digest(p) == hashlib.sha256(data).hexdigest()


def test_file_digest_is_memoised_until_the_file_changes(tmp_path: Path) -> None:
    p = _file(tmp_path)
    calls = {"n": 0}
    real = cache._hash_file

    def counting(path: Path) -> str:
        calls["n"] += 1
        return real(path)

    cache._hash_file = counting  # type: ignore[assignment]
    try:
        first = cache.file_digest(p)
        assert cache.file_digest(p) == first and calls["n"] == 1
        p.write_bytes(b"ISO-10303-21;\nDATA;\n" + b"changed")
        os.utime(p, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))
        assert cache.file_digest(p) != first and calls["n"] == 2
    finally:
        cache._hash_file = real  # type: ignore[assignment]


def test_cache_key_depends_on_content_and_options_not_on_the_name(tmp_path: Path) -> None:
    a = _file(tmp_path, name="a.step")
    b = _file(tmp_path, name="renamed.step")
    c = _file(tmp_path, content=b"other", name="c.step")
    k = cache.cache_key(a, OPTS)
    assert cache.cache_key(b, OPTS) == k, "same bytes under another name hit the same entry"
    assert cache.cache_key(c, OPTS) != k
    assert cache.cache_key(a, AnalyzeOptions(no_timestamp=True, material="alu")) != k
    ctx = tmp_path / "design_context.yaml"
    ctx.write_text("purpose: x\n", encoding="utf-8")
    assert cache.cache_key(a, OPTS, ctx) != k


def test_cli_export_mcp_and_ui_share_one_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "c"))
    p = _file(tmp_path)
    key = cache.cache_key(p, OPTS)
    assert jobs.job_out_dir(p, OPTS).name == key[:16], "MCP jobs"
    assert cache.entry_dir(p, OPTS) == jobs.job_out_dir(p, OPTS)
    # the CLI export's stamp key is built from the same file digest
    seen: list[Path] = []
    real = cache.file_digest

    def spy(path: Path | str) -> str:
        seen.append(Path(path))
        return real(path)

    monkeypatch.setattr(cache, "file_digest", spy)
    exporter.export_key(p, OPTS, None, {})
    assert seen == [p], "CLI export"
    from stepscribe.ui.worker import job_cache_key

    ui_params = {"material": None, "density": None, "up": "+Z", "front": "-Y", "interference": True}
    ui_opts = AnalyzeOptions(
        up="+Z", front="-Y", check_interference=True, no_timestamp=True, material=None
    )
    assert job_cache_key(p, ui_params) == cache.cache_key(p, ui_opts), "web UI"


# ---------------------------------------------------------- stamps and eviction
def _entry(root: Path, name: str, size: int, age_s: float) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "blob.bin").write_bytes(b"x" * size)
    t = time.time() - age_s
    os.utime(d / "blob.bin", (t, t))
    os.utime(d, (t, t))
    return d


def test_eviction_removes_least_recently_used_entries_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "c"))
    root = cache.cache_root()
    old = _entry(root, "old", 600_000, 300)
    mid = _entry(root, "mid", 600_000, 200)
    new = _entry(root, "new", 600_000, 100)
    removed = cache.evict(max_bytes=1_300_000)
    assert [p.name for p in removed] == ["old"]
    assert not old.exists() and mid.exists() and new.exists()
    removed = cache.evict(max_bytes=700_000)
    assert [p.name for p in removed] == ["mid"] and new.exists()


def test_using_an_entry_makes_it_recent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "c"))
    root = cache.cache_root()
    old = _entry(root, "old", 600_000, 300)
    _entry(root, "newer", 600_000, 100)
    cache.touch(old)
    assert [p.name for p in cache.evict(max_bytes=700_000)] == ["newer"]


def test_the_entry_just_written_is_never_evicted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "c"))
    only = _entry(cache.cache_root(), "only", 900_000, 10)
    assert cache.evict(max_bytes=1, keep=[only]) == []
    assert only.exists()


def test_info_and_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "c"))
    root = cache.cache_root()
    _entry(root, "a", 1000, 5)
    _entry(root, "b", 2000, 5)
    info = cache.info()
    assert info["entries"] == 2 and info["bytes"] >= 3000 and info["path"] == str(root)
    assert cache.clear() == 2 and cache.info()["entries"] == 0 and root.is_dir()


def _write_entry(root: Path, key: str, report: dict[str, Any], stamp: dict[str, Any]) -> Path:
    folder = root / key[:16] / "x_stepscribe"
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (folder / ".stepscribe_export.json").write_text(json.dumps(stamp), encoding="utf-8")
    return folder


def test_a_corrupt_or_stale_entry_is_not_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step_files: dict[str, Path]
) -> None:
    from stepscribe.api import analyze_full

    monkeypatch.setenv("STEPSCRIBE_CACHE", str(tmp_path / "c"))
    p = step_files["plate_4xM3"]
    result = exporter.export(p, jobs.job_out_dir(p, OPTS), OPTS, images=False)
    assert cache.load_report(p, OPTS) is not None, "a good entry loads"
    folder = Path(result.folder)
    stamp = folder / ".stepscribe_export.json"
    good = stamp.read_text(encoding="utf-8")

    stamp.write_text("{not json", encoding="utf-8")  # corrupt stamp
    assert cache.load_report(p, OPTS) is None
    stamp.write_text(good, encoding="utf-8")
    assert cache.load_report(p, OPTS) is not None

    stale = json.loads(good)
    stale["file_sha256"] = "0" * 64  # written for another file
    stamp.write_text(json.dumps(stale), encoding="utf-8")
    assert cache.load_report(p, OPTS) is None
    stamp.write_text(good, encoding="utf-8")

    report = folder / "data" / "report.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    data["meta"]["schema_version"] = "0.0.1"  # an older layout
    report.write_text(json.dumps(data), encoding="utf-8")
    assert cache.load_report(p, OPTS) is None

    report.unlink()  # a file the stamp lists is gone
    assert cache.load_report(p, OPTS) is None
    assert analyze_full is not None
