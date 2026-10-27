"""tests/slow_tests.txt names tests that exist, so a rename cannot silently put a test back in the fast run."""

from __future__ import annotations

import ast
from pathlib import Path

import conftest

ROOT = Path(__file__).parent


def test_every_listed_slow_test_exists() -> None:
    missing = []
    for node_id in sorted(conftest._slow_ids()):
        file_part, _, name = node_id.partition("::")
        path = ROOT.parent / file_part
        func = name.split("[")[0]
        defined = path.is_file() and any(
            isinstance(n, ast.FunctionDef) and n.name == func
            for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        )
        if not defined:
            missing.append(node_id)
    assert not missing, f"tests/slow_tests.txt lists tests that are gone: {missing}"
