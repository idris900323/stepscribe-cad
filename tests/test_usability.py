"""H5: ease of use: python -m, pins, the OCCT check, friendly errors, README and sdist."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stepscribe import __version__, envcheck
from stepscribe.cli import app

ROOT = Path(__file__).parent.parent
runner = CliRunner()


# ------------------------------------------------------------ python -m stepscribe
def test_python_dash_m_stepscribe_works() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "stepscribe", "version"], capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr[-500:]
    assert __version__ in out.stdout and "OpenCASCADE" in out.stdout


def test_readme_and_hints_recommend_python_dash_m() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python -m stepscribe" in readme and "py -m stepscribe" in readme
    assert "close and reopen the terminal" not in readme
    skill = (ROOT / "skills" / "stepscribe" / "SKILL.md").read_text(encoding="utf-8")
    assert "python -m stepscribe" in skill


# ------------------------------------------------------------------------- pins
def _deps() -> dict[str, str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    pools = [data["project"]["dependencies"], *data["project"]["optional-dependencies"].values()]
    for pool in pools:
        for spec in pool:
            m = re.match(r"([A-Za-z0-9_.-]+)(.*)", spec)
            assert m
            out[m.group(1).lower()] = m.group(2).replace(" ", "")
    return out


def test_dependencies_are_pinned_to_what_is_tested() -> None:
    deps = _deps()
    assert deps["cadquery-ocp"] == ">=8.0,<9"
    for name in ("mcp", "vtk", "numpy", "pydantic", "typer"):
        assert "<" in deps[name], f"{name} needs an upper bound: {deps[name]!r}"


def test_the_installed_versions_satisfy_the_pins() -> None:
    from importlib.metadata import version

    from packaging.specifiers import SpecifierSet

    deps = _deps()
    for name in ("cadquery-ocp", "mcp", "vtk", "numpy", "pydantic", "typer"):
        assert version(name) in SpecifierSet(deps[name]), name


def test_ci_tests_python_313() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert '"3.13"' in ci


# ----------------------------------------------------------------- the OCCT check
ONE_LINE = 'stepscribe needs OCCT 8; run: python -m pip install -U "cadquery-ocp>=8,<9"'


def test_old_opencascade_fails_with_one_line() -> None:
    with pytest.raises(envcheck.EnvironmentProblem) as e:
        envcheck.check_occt("7.7.2.0")
    assert str(e.value) == ONE_LINE
    envcheck.check_occt("8.0.1.0")  # fine
    with pytest.raises(envcheck.EnvironmentProblem):
        envcheck.check_occt("9.0.0.0")


def test_analysis_checks_the_version_before_it_starts(
    monkeypatch: pytest.MonkeyPatch, step_files: dict[str, Path]
) -> None:
    from stepscribe.api import analyze_full

    monkeypatch.setattr(envcheck, "installed_occt", lambda: "7.7.2.0")
    with pytest.raises(envcheck.EnvironmentProblem, match="needs OCCT 8"):
        analyze_full(step_files["plate_4xM3"])


def test_the_command_line_shows_the_one_line_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, step_files: dict[str, Path], tmp_path: Path
) -> None:
    monkeypatch.setattr(envcheck, "installed_occt", lambda: "7.7.2.0")
    res = runner.invoke(app, ["analyze", str(step_files["plate_4xM3"]), "-o", str(tmp_path)])
    assert res.exit_code == 1
    assert ONE_LINE in res.output and "Traceback" not in res.output


# ------------------------------------------------------------------ friendly errors
def test_known_errors_become_one_sentence_with_a_suggestion() -> None:
    from stepscribe.errors import friendly_message
    from stepscribe.io.step_reader import StepReadError
    from stepscribe.render.raster import RenderUnavailable

    cases = {
        FileNotFoundError("nope.step"): ("nope.step", "path"),
        StepReadError("cannot parse STEP file: a.step"): ("a.step", "STEP"),
        StepReadError(
            "x.step has assembly structure but no geometry: its parts are external references"
        ): (
            "external",
            "next to it",
        ),
        RenderUnavailable("no GL"): ("images", "--no-images"),
        MemoryError(): ("memory", "STEPSCRIBE_WORKERS=1"),
        TimeoutError(): ("too long", "--timeout-s"),
        ModuleNotFoundError("No module named 'mcp'", name="mcp"): ("mcp", "pip install"),
    }
    for exc, (word, hint) in cases.items():
        msg = friendly_message(exc)
        assert msg and "\n" not in msg, exc
        assert word.lower() in msg.lower() and hint in msg, (exc, msg)
    assert friendly_message(ValueError("a bug")) is None, "unknown errors keep their traceback"


def test_a_file_that_is_not_step_gets_a_sentence_and_debug_shows_the_traceback(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "notes.step"
    bad.write_text("this is not a STEP file\n", encoding="utf-8")
    res = runner.invoke(app, ["analyze", str(bad), "-o", str(tmp_path / "o")])
    assert res.exit_code == 1 and "Traceback" not in res.output
    assert "notes.step" in res.output and "STEP" in res.output
    dbg = runner.invoke(app, ["--debug", "analyze", str(bad), "-o", str(tmp_path / "o2")])
    assert dbg.exit_code != 0 and dbg.exception is not None


# ---------------------------------------------------------------------- the README
def _load_script(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_readme_defaults_are_generated_from_the_cli() -> None:
    gen = _load_script("update_readme_defaults")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = readme.split("<!-- cli-defaults:start -->")[1].split("<!-- cli-defaults:end -->")[0]
    assert block.strip() == gen.render_block().strip(), (
        "run: python scripts/update_readme_defaults.py"
    )
    assert "stepscribe_export" in block and "8765" in block, "the real defaults are listed"
    prose = readme.replace(block, "")
    assert "writes to `./out`" not in prose


def test_readme_links_are_absolute() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    relative = [m.group(0) for m in re.finditer(r"\]\((?!https?://|#|mailto:)[^)]*\)", readme)]
    assert not relative, relative
    assert "https://github.com/idris900323/stepscribe-cad/blob/main/LICENSE" in readme


# ----------------------------------------------------------------------- the sdist
def test_the_sdist_stays_small(tmp_path: Path) -> None:
    pytest.importorskip("build")
    subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(tmp_path)],
        check=True,
        capture_output=True,
        cwd=ROOT,
        timeout=600,
    )
    sdist = next(tmp_path.glob("*.tar.gz"))
    assert sdist.stat().st_size < 3 * 1024 * 1024, f"{sdist.stat().st_size / 1e6:.1f} MB"
    import tarfile

    with tarfile.open(sdist) as tf:
        names = tf.getnames()
    assert not any("docs/media" in n or ("golden" in n and n.endswith(".png")) for n in names)
    assert any(n.endswith("stepscribe/cli.py") for n in names)


def test_large_media_never_ends_up_in_the_sdist(tmp_path: Path) -> None:
    """A demo video under docs/media (the audit's 9.2 MB sdist) must be left out."""
    pytest.importorskip("build")
    import os
    import shutil
    import tarfile

    proj = tmp_path / "proj"
    (proj / "stepscribe").mkdir(parents=True)
    (proj / "docs" / "media").mkdir(parents=True)
    (proj / "tests" / "golden").mkdir(parents=True)
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy(ROOT / name, proj / name)
    (proj / "stepscribe" / "__init__.py").write_text('__version__ = "0.0.1"\n', encoding="utf-8")
    (proj / "docs" / "media" / "demo.mp4").write_bytes(os.urandom(5 * 1024 * 1024))
    (proj / "tests" / "golden" / "shot.png").write_bytes(os.urandom(200_000))
    (proj / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(tmp_path / "out")],
        check=True,
        capture_output=True,
        cwd=proj,
        timeout=600,
    )
    sdist = next((tmp_path / "out").glob("*.tar.gz"))
    with tarfile.open(sdist) as tf:
        names = tf.getnames()
    assert not any(n.endswith("demo.mp4") or n.endswith("shot.png") for n in names)
    assert any(n.endswith("docs/guide.md") for n in names)
    assert sdist.stat().st_size < 1024 * 1024
