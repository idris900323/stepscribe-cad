"""The package on PyPI is stepscribe-cad (the command is stepscribe). Every install line must say so."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".j2",
    ".html",
    ".cfg",
    ".bat",
    ".sh",
}
# "pip install stepscribe" (also with flags or a quote) not followed by "-cad", and the extras form "stepscribe[".
WRONG_INSTALL = re.compile(r"""pip install\s+(?:-\S+\s+)*["']?stepscribe(?![-\w])""")
WRONG_EXTRA = re.compile(r"""(?<![-\w])stepscribe\[""")
THIS_FILE = Path(__file__).resolve()


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8")
    files = [ROOT / n for n in out.split("\0") if n]
    return [
        p
        for p in files
        if p.suffix.lower() in TEXT_SUFFIXES and p.is_file() and p.resolve() != THIS_FILE
    ]


def _wrong_lines() -> list[str]:
    found: list[str] = []
    for p in _tracked_text_files():
        for i, line in enumerate(p.read_text("utf-8", errors="replace").splitlines(), 1):
            if WRONG_INSTALL.search(line) or WRONG_EXTRA.search(line):
                found.append(f"{p.relative_to(ROOT).as_posix()}:{i}: {line.strip()[:120]}")
    return found


def test_no_file_tells_users_to_install_the_wrong_package_name() -> None:
    assert _wrong_lines() == []


def test_the_guard_catches_the_wrong_forms_and_lets_the_right_ones_pass() -> None:
    wrong = [
        "pip install stepscribe",
        'python -m pip install "stepscribe"',
        "pip install -U stepscribe",
        "pip install stepscribe[mcp]",
        'needs: "stepscribe[robot]"',
        "pip install 'stepscribe[llm]'",
    ]
    right = [
        "pip install stepscribe-cad",
        'python -m pip install "stepscribe-cad[mcp]"',
        "pip install -U stepscribe-cad",
        "the stepscribe command",
        "pip install -e .[dev]",
    ]
    for s in wrong:
        assert WRONG_INSTALL.search(s) or WRONG_EXTRA.search(s), s
    for s in right:
        assert not (WRONG_INSTALL.search(s) or WRONG_EXTRA.search(s)), s
