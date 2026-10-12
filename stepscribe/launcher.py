# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Desktop launchers: double-click an icon, the page opens (``stepscribe shortcut``).

Each launcher runs the Python that installed stepscribe by its absolute path, so it works even when
Python's Scripts folder is not on PATH. Nothing needs admin rights, and a file that is not ours is
never overwritten without ``--force``.  If stepscribe is no longer installed for that Python, the
launcher says so in one sentence and waits instead of flashing closed.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MARK = "stepscribe launcher"
DATA = Path(__file__).parent / "data"
ICON_ICO = DATA / "stepscribe.ico"
ICON_PNG = DATA / "stepscribe.png"
PS_SCRIPT = DATA / "make_shortcut.ps1"
REINSTALL = "-m pip install stepscribe-cad"

RunPowerShell = Callable[[list[str]], str]


@dataclass(frozen=True)
class Locations:
    """Where the launchers go (patched in tests)."""

    platform: str  # win32 | darwin | linux
    python: str  # absolute path of the interpreter that has stepscribe
    desktop: Path
    app_dir: Path  # Windows: %LOCALAPPDATA%\stepscribe ; Linux: ~/.local/share/applications
    icon: Path


@dataclass(frozen=True)
class Made:
    path: Path
    skipped: bool = False
    reason: str = ""


def default_locations() -> Locations:
    home = Path.home()
    desktop = home / "Desktop"
    if sys.platform == "win32":
        one_drive = (
            Path(os.environ.get("OneDrive", "")) / "Desktop" if os.environ.get("OneDrive") else None
        )
        if not desktop.is_dir() and one_drive and one_drive.is_dir():
            desktop = one_drive
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return Locations("win32", sys.executable, desktop, local / "stepscribe", ICON_ICO)
    if sys.platform == "darwin":
        return Locations("darwin", sys.executable, desktop, home / "Applications", ICON_PNG)
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return Locations("linux", sys.executable, desktop, data / "applications", ICON_PNG)


# ------------------------------------------------------------------- contents
def bat_text(python: str) -> str:
    """The Windows launcher. ``%`` is doubled; ``goto`` avoids ``(`` ``)`` problems in paths."""
    py = '"' + python.replace("%", "%%") + '"'
    lines = [
        "@echo off",
        f"rem {MARK} (made by: stepscribe shortcut)",
        "title stepscribe",
        f'{py} -c "import stepscribe" 2>nul',
        "if errorlevel 1 goto missing",
        f"{py} -m stepscribe ui",
        "if errorlevel 1 pause",
        "exit /b 0",
        ":missing",
        "echo stepscribe is no longer installed for this Python.",
        f"echo Reinstall it with:  {py} {REINSTALL}",
        "pause",
        "exit /b 1",
        "",
    ]
    return "\r\n".join(lines)


def command_text(python: str) -> str:
    """The macOS ``.command`` launcher."""
    q = shlex.quote(python)
    return (
        "#!/bin/bash\n"
        f"# {MARK} (made by: stepscribe shortcut)\n"
        f"if ! {q} -c 'import stepscribe' 2>/dev/null; then\n"
        "  echo 'stepscribe is no longer installed for this Python.'\n"
        "  echo 'Reinstall it with the same Python:'\n"
        f"  echo {q} {REINSTALL}\n"
        "  read -n 1 -s -r -p 'Press any key to close'\n"
        "  exit 1\n"
        "fi\n"
        f"exec {q} -m stepscribe ui\n"
    )


def _exec_quote(arg: str) -> str:
    """Quote one argument for the Exec= key of a .desktop file."""
    out = arg
    for ch in ("\\", '"', "`", "$"):
        out = out.replace(ch, "\\" + ch)
    return '"' + out.replace("%", "%%") + '"'


def desktop_entry_text(python: str, icon: Path) -> str:
    """The Linux ``.desktop`` launcher (no terminal)."""
    return (
        "[Desktop Entry]\n"
        f"# {MARK} (made by: stepscribe shortcut)\n"
        "Type=Application\n"
        "Name=stepscribe\n"
        "Comment=Turn a STEP file into a plain-language description of the design\n"
        f"Exec={_exec_quote(python)} -m stepscribe ui\n"
        "Terminal=false\n"
        f"Icon={icon}\n"
        "Categories=Graphics;Engineering;\n"
    )


# ------------------------------------------------------------------ PowerShell
def default_run_ps(argv: list[str]) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or "PowerShell could not create the shortcut")
    return done.stdout.strip()


def _ps_argv(mode: str, link: Path, **fields: str) -> list[str]:
    argv = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PS_SCRIPT),
        "-Mode",
        mode,
        "-LinkPath",
        str(link),
    ]
    for key, value in fields.items():
        argv += [f"-{key}", value]
    return argv


# ----------------------------------------------------------------------- files
def _is_ours(path: Path, loc: Locations, run_ps: RunPowerShell) -> bool:
    if not path.exists():
        return True
    if path.suffix == ".lnk":
        return run_ps(_ps_argv("read", path)).strip() == MARK
    try:
        return MARK in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _write(
    path: Path,
    text: str,
    loc: Locations,
    force: bool,
    run_ps: RunPowerShell,
    mode: int | None = None,
) -> Made:
    if not force and not _is_ours(path, loc, run_ps):
        return Made(path, True, "it is not a stepscribe launcher; use --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    if mode is not None and sys.platform != "win32":
        path.chmod(mode)
    return Made(path)


def create(
    loc: Locations,
    force: bool = False,
    minimised: bool = False,
    run_ps: RunPowerShell = default_run_ps,
) -> list[Made]:
    """Write the launcher(s) for this OS; returns what was written or skipped."""
    made: list[Made] = []
    if loc.platform == "win32":
        bat = loc.app_dir / "stepscribe.bat"
        made.append(_write(bat, bat_text(loc.python), loc, force, run_ps))
        link = loc.desktop / "stepscribe.lnk"
        if made[0].skipped:
            return made
        if not force and not _is_ours(link, loc, run_ps):
            made.append(
                Made(link, True, "it is not a stepscribe launcher; use --force to replace it")
            )
            return made
        link.parent.mkdir(parents=True, exist_ok=True)
        run_ps(
            _ps_argv(
                "create",
                link,
                Target=str(bat),
                WorkDir=str(loc.app_dir),
                Icon=str(loc.icon),
                Description=MARK,
                WindowStyle="7" if minimised else "1",
            )
        )
        made.append(Made(link))
    elif loc.platform == "darwin":
        made.append(
            _write(
                loc.desktop / "stepscribe.command",
                command_text(loc.python),
                loc,
                force,
                run_ps,
                stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP,
            )
        )
    else:
        text = desktop_entry_text(loc.python, loc.icon)
        made.append(_write(loc.app_dir / "stepscribe.desktop", text, loc, force, run_ps, 0o755))
        if loc.desktop.is_dir():
            made.append(_write(loc.desktop / "stepscribe.desktop", text, loc, force, run_ps, 0o755))
    return made


def _targets(loc: Locations) -> list[Path]:
    if loc.platform == "win32":
        return [loc.app_dir / "stepscribe.bat", loc.desktop / "stepscribe.lnk"]
    if loc.platform == "darwin":
        return [loc.desktop / "stepscribe.command"]
    return [loc.app_dir / "stepscribe.desktop", loc.desktop / "stepscribe.desktop"]


def remove(loc: Locations, run_ps: RunPowerShell = default_run_ps) -> list[Path]:
    """Delete the launchers that stepscribe made; anything else with the same name stays."""
    gone: list[Path] = []
    for path in _targets(loc):
        if path.exists() and _is_ours(path, loc, run_ps):
            path.unlink()
            gone.append(path)
    if loc.platform == "win32":
        try:
            loc.app_dir.rmdir()
        except OSError:
            pass
    return gone
