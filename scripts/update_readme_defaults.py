# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Write the option defaults in README.md from the real command line, so they cannot drift.

python scripts/update_readme_defaults.py          # rewrite the block between the markers
python scripts/update_readme_defaults.py --check  # exit 1 if README.md is out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
START, END = "<!-- cli-defaults:start -->", "<!-- cli-defaults:end -->"
COMMANDS = ("export", "pack", "analyze", "ui", "mcp")


def _shown(value: object) -> str | None:
    if value is None or value is False or value == () or value == "":
        return None
    return str(value).replace("\\", "/")


def render_block() -> str:
    """Markdown list of the option defaults of the main commands."""
    from stepscribe.cli import app

    root = typer.main.get_command(app)
    lines = [
        "Defaults (generated from the command line, `python scripts/update_readme_defaults.py`):",
        "",
    ]
    for name in COMMANDS:
        cmd = root.commands[name]
        items = []
        for param in cmd.params:
            if not hasattr(param, "opts") or getattr(param, "is_flag", False):
                continue
            shown = _shown(param.default)
            if shown is not None and param.name != "help":
                items.append(f"`{max(param.opts, key=len)}` = `{shown}`")
        if items:
            lines.append(f"- `stepscribe {name}`: " + ", ".join(items))
    return "\n".join(lines)


def updated_readme(text: str) -> str:
    head, rest = text.split(START, 1)
    _old, tail = rest.split(END, 1)
    return f"{head}{START}\n{render_block()}\n{END}{tail}"


def main(argv: list[str]) -> int:
    text = README.read_text(encoding="utf-8")
    new = updated_readme(text)
    if "--check" in argv:
        if new != text:
            print("README.md defaults are out of date: run scripts/update_readme_defaults.py")
            return 1
        return 0
    README.write_text(new, encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
