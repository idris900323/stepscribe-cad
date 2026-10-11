"""H6: `stepscribe shortcut` writes the right launcher for each OS, safely and removably."""

from __future__ import annotations

import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stepscribe import launcher
from stepscribe.cli import app

WIN_PY = r"C:\Program Files\Python 312\python.exe"
POSIX_PY = "/home/me/my env/bin/python"


class FakePowerShell:
    """Records the argument lists given to PowerShell; remembers shortcuts it 'created'."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.descriptions: dict[str, str] = {}

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(list(argv))
        mode = argv[argv.index("-Mode") + 1]
        link = argv[argv.index("-LinkPath") + 1]
        if mode == "create":
            Path(link).write_text("lnk", encoding="utf-8")
            self.descriptions[link] = argv[argv.index("-Description") + 1]
            return ""
        return self.descriptions.get(link, "")


def locations(tmp_path: Path, platform: str, python: str) -> launcher.Locations:
    desktop = tmp_path / "Desktop"
    desktop.mkdir(exist_ok=True)
    return launcher.Locations(
        platform=platform,
        python=python,
        desktop=desktop,
        app_dir=tmp_path / ("stepscribe" if platform == "win32" else "applications"),
        icon=tmp_path / ("stepscribe.ico" if platform == "win32" else "stepscribe.png"),
    )


# ------------------------------------------------------------------- Windows
EXPECTED_BAT = "\r\n".join(
    [
        "@echo off",
        "rem stepscribe launcher (made by: stepscribe shortcut)",
        "title stepscribe",
        '"C:\\Program Files\\Python 312\\python.exe" -c "import stepscribe" 2>nul',
        "if errorlevel 1 goto missing",
        '"C:\\Program Files\\Python 312\\python.exe" -m stepscribe ui',
        "if errorlevel 1 pause",
        "exit /b 0",
        ":missing",
        "echo stepscribe is no longer installed for this Python.",
        'echo Reinstall it with:  "C:\\Program Files\\Python 312\\python.exe" -m pip install stepscribe-cad',
        "pause",
        "exit /b 1",
        "",
    ]
)


def test_windows_batch_file_has_the_exact_contents(tmp_path: Path) -> None:
    ps = FakePowerShell()
    loc = locations(tmp_path, "win32", WIN_PY)
    made = launcher.create(loc, run_ps=ps)
    bat = loc.app_dir / "stepscribe.bat"
    assert bat.read_bytes().decode("utf-8") == EXPECTED_BAT
    assert launcher.bat_text(WIN_PY) == EXPECTED_BAT
    assert {m.path for m in made} == {bat, loc.desktop / "stepscribe.lnk"}


def test_percent_signs_and_spaces_in_the_interpreter_path_are_quoted() -> None:
    text = launcher.bat_text(r"C:\Users\100%\a b\(x86)\python.exe")
    assert '"C:\\Users\\100%%\\a b\\(x86)\\python.exe" -m stepscribe ui' in text
    assert "%" not in text.replace("%%", "")


def test_windows_shortcut_is_made_with_a_fixed_argument_list(tmp_path: Path) -> None:
    ps = FakePowerShell()
    loc = locations(tmp_path, "win32", WIN_PY)
    launcher.create(loc, run_ps=ps)
    create = next(c for c in ps.calls if "create" in c)
    assert create[0].lower().endswith("powershell.exe") or create[0] == "powershell.exe"
    assert create[1:7] == [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(launcher.PS_SCRIPT),
    ]
    flags = dict(zip(create[7::2], create[8::2], strict=True))
    assert flags == {
        "-Mode": "create",
        "-LinkPath": str(loc.desktop / "stepscribe.lnk"),
        "-Target": str(loc.app_dir / "stepscribe.bat"),
        "-WorkDir": str(loc.app_dir),
        "-Icon": str(loc.icon),
        "-Description": launcher.MARK,
        "-WindowStyle": "1",
    }
    assert all(isinstance(a, str) for a in create), "no shell string is ever built"
    ps2 = FakePowerShell()
    launcher.create(loc, run_ps=ps2, minimised=True, force=True)
    assert "7" in next(c for c in ps2.calls if "create" in c)


def test_nothing_that_is_not_ours_is_overwritten_without_force(tmp_path: Path) -> None:
    loc = locations(tmp_path, "win32", WIN_PY)
    loc.app_dir.mkdir(parents=True)
    foreign = loc.app_dir / "stepscribe.bat"
    foreign.write_bytes(b"echo mine\r\n")
    ps = FakePowerShell()
    made = launcher.create(loc, run_ps=ps)
    assert foreign.read_bytes() == b"echo mine\r\n"
    skipped = [m for m in made if m.skipped]
    assert skipped and skipped[0].path == foreign and "--force" in skipped[0].reason
    foreign.unlink()
    launcher.create(loc, run_ps=ps)  # now the batch file is ours again
    # a shortcut with another description is foreign too
    (loc.desktop / "stepscribe.lnk").write_text("x", encoding="utf-8")
    ps.descriptions[str(loc.desktop / "stepscribe.lnk")] = "my own link"
    made = launcher.create(loc, run_ps=ps)
    assert any(m.path.suffix == ".lnk" and m.skipped for m in made)
    forced = launcher.create(loc, run_ps=ps, force=True)
    assert not any(m.skipped for m in forced)
    assert foreign.read_bytes().decode("utf-8") == EXPECTED_BAT


def test_our_own_files_are_refreshed_without_force(tmp_path: Path) -> None:
    ps = FakePowerShell()
    loc = locations(tmp_path, "win32", WIN_PY)
    launcher.create(loc, run_ps=ps)
    again = launcher.create(
        launcher.Locations(**{**loc.__dict__, "python": r"D:\Py\python.exe"}), run_ps=ps
    )
    assert not any(m.skipped for m in again)
    assert "D:\\Py\\python.exe" in (loc.app_dir / "stepscribe.bat").read_text(encoding="utf-8")


def test_remove_deletes_only_our_launchers(tmp_path: Path) -> None:
    ps = FakePowerShell()
    loc = locations(tmp_path, "win32", WIN_PY)
    launcher.create(loc, run_ps=ps)
    other = loc.desktop / "keep me.txt"
    other.write_text("x", encoding="utf-8")
    gone = launcher.remove(loc, run_ps=ps)
    assert {p.name for p in gone} == {"stepscribe.bat", "stepscribe.lnk"}
    assert other.exists() and not (loc.app_dir / "stepscribe.bat").exists()
    # a foreign file with our name stays
    (loc.desktop / "stepscribe.lnk").write_text("x", encoding="utf-8")
    ps.descriptions[str(loc.desktop / "stepscribe.lnk")] = "someone else's"
    assert launcher.remove(loc, run_ps=ps) == []
    assert (loc.desktop / "stepscribe.lnk").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows PowerShell")
def test_a_real_shortcut_is_created_read_and_removed(tmp_path: Path) -> None:
    loc = locations(tmp_path, "win32", sys.executable)
    loc = launcher.Locations(**{**loc.__dict__, "icon": launcher.ICON_ICO})
    made = launcher.create(loc)
    lnk = loc.desktop / "stepscribe.lnk"
    assert lnk.is_file() and not any(m.skipped for m in made)
    desc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher.PS_SCRIPT),
            "-Mode",
            "read",
            "-LinkPath",
            str(lnk),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()
    assert desc == launcher.MARK
    assert lnk in launcher.remove(loc)
    assert not lnk.exists()


# --------------------------------------------------------------------- macOS
def test_macos_command_file(tmp_path: Path) -> None:
    py = "/Users/me/it's here/python3"
    loc = locations(tmp_path, "darwin", py)
    made = launcher.create(loc)
    path = loc.desktop / "stepscribe.command"
    text = path.read_text(encoding="utf-8")
    assert text == launcher.command_text(py)
    assert text.startswith("#!/bin/bash\n# stepscribe launcher (made by: stepscribe shortcut)\n")
    q = shlex.quote(py)
    assert f"{q} -c 'import stepscribe'" in text and f"exec {q} -m stepscribe ui" in text
    assert (
        "python3 -m pip install stepscribe-cad" in text or "-m pip install stepscribe-cad" in text
    )
    assert [m.path for m in made] == [path]
    if sys.platform != "win32":
        assert path.stat().st_mode & stat.S_IXUSR


# --------------------------------------------------------------------- Linux
def test_linux_desktop_entry(tmp_path: Path) -> None:
    loc = locations(tmp_path, "linux", POSIX_PY)
    made = launcher.create(loc)
    entry = loc.app_dir / "stepscribe.desktop"
    text = entry.read_text(encoding="utf-8")
    assert text == launcher.desktop_entry_text(POSIX_PY, loc.icon)
    lines = text.splitlines()
    assert lines[0] == "[Desktop Entry]" and "# stepscribe launcher" in text
    assert 'Exec="/home/me/my env/bin/python" -m stepscribe ui' in lines
    assert "Terminal=false" in lines and f"Icon={loc.icon}" in lines and "Type=Application" in lines
    assert entry in {m.path for m in made}
    assert (loc.desktop / "stepscribe.desktop") in {m.path for m in made}


def test_linux_entry_escapes_what_the_format_requires() -> None:
    text = launcher.desktop_entry_text('/opt/50%/py "x"/python', Path("/i.png"))
    assert 'Exec="/opt/50%%/py \\"x\\"/python" -m stepscribe ui' in text


def test_linux_without_a_desktop_folder_only_writes_the_applications_entry(tmp_path: Path) -> None:
    loc = locations(tmp_path, "linux", POSIX_PY)
    loc.desktop.rmdir()
    made = launcher.create(loc)
    assert [m.path.name for m in made] == ["stepscribe.desktop"]
    assert launcher.remove(loc) == [loc.app_dir / "stepscribe.desktop"]


# ------------------------------------------------------------ icons and command
def test_the_icons_ship_with_the_package() -> None:
    from PIL import Image

    with Image.open(launcher.ICON_ICO) as ico:
        assert ico.format == "ICO" and max(ico.info.get("sizes", {(0, 0)})) >= (32, 32)
    with Image.open(launcher.ICON_PNG) as png:
        assert png.format == "PNG" and png.size[0] >= 64
    assert launcher.PS_SCRIPT.is_file()


def test_the_shortcut_command_prints_where_it_wrote_and_removes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loc = locations(tmp_path, "linux", POSIX_PY)
    monkeypatch.setattr(launcher, "default_locations", lambda: loc)
    runner = CliRunner()
    res = runner.invoke(app, ["shortcut"])
    assert res.exit_code == 0, res.output
    assert str(loc.app_dir / "stepscribe.desktop") in res.output.replace("\n", "")
    gone = runner.invoke(app, ["shortcut", "--remove"])
    assert gone.exit_code == 0 and "Removed" in gone.output
    assert not (loc.app_dir / "stepscribe.desktop").exists()


def test_the_shortcut_needs_no_admin_rights_and_uses_user_folders() -> None:
    loc = launcher.default_locations()
    assert Path.home() in loc.desktop.parents or loc.desktop == Path.home()
    assert loc.python == sys.executable and Path(loc.python).is_absolute()
