"""H5: `stepscribe doctor` explains what is wrong and how to fix it, one line per problem."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys

from typer.testing import CliRunner

from stepscribe import doctor
from stepscribe.cli import app


def healthy() -> doctor.Probe:
    return doctor.Probe(
        python=lambda: (3, 12, 4),
        stepscribe=lambda: "0.1.3",
        occt=lambda: "8.0.1.0",
        vtk=lambda: "9.6.2",
        mcp=lambda: "2.3.0",
        rendering=lambda: True,
        cache=lambda: {
            "path": "/home/me/.cache/stepscribe",
            "entries": 2,
            "bytes": 5_000_000,
            "fallback_reason": None,
        },
        free_ram=lambda: 16 * 1024**3,
        cpus=lambda: 8,
    )


def by_name(checks: list[doctor.Check]) -> dict[str, doctor.Check]:
    return {c.name: c for c in checks}


def test_a_healthy_machine_has_no_problems() -> None:
    checks = doctor.run_checks(healthy())
    assert all(c.level == "ok" for c in checks), [(c.name, c.level) for c in checks]
    names = [c.name for c in checks]
    for want in (
        "Python",
        "stepscribe",
        "OpenCASCADE",
        "VTK",
        "MCP",
        "Rendering",
        "Cache",
        "Memory",
        "CPUs",
    ):
        assert want in names
    assert "2 entries" in by_name(checks)["Cache"].detail


def check_with(**override: object) -> doctor.Check:
    probe = dataclasses.replace(healthy(), **override)
    name = {
        "python": "Python",
        "occt": "OpenCASCADE",
        "vtk": "VTK",
        "mcp": "MCP",
        "rendering": "Rendering",
        "cache": "Cache",
        "free_ram": "Memory",
        "cpus": "CPUs",
    }[next(iter(override))]
    return by_name(doctor.run_checks(probe))[name]


def test_old_python_is_a_failure_with_a_fix() -> None:
    c = check_with(python=lambda: (3, 9, 1))
    assert c.level == "fail" and "3.11" in c.fix and "python.org" in c.fix


def test_missing_and_old_opencascade_get_the_pip_command() -> None:
    missing = check_with(occt=lambda: None)
    assert missing.level == "fail" and 'python -m pip install "cadquery-ocp>=8,<9"' in missing.fix
    old = check_with(occt=lambda: "7.7.2.0")
    assert old.level == "fail" and "OCCT 8" in old.detail
    assert 'python -m pip install -U "cadquery-ocp>=8,<9"' in old.fix
    future = check_with(occt=lambda: "9.0.0.0")
    assert future.level == "warn" and "cadquery-ocp>=8,<9" in future.fix


def test_missing_vtk_and_mcp() -> None:
    vtk = check_with(vtk=lambda: None)
    assert vtk.level == "fail" and "pip install vtk" in vtk.fix
    mcp = check_with(mcp=lambda: None)
    assert mcp.level == "warn" and "optional" in mcp.detail and "stepscribe-cad[mcp]" in mcp.fix


def test_rendering_that_does_not_work_says_what_to_do_on_each_os() -> None:
    c = check_with(rendering=lambda: False)
    assert c.level == "warn" and "without images" in c.detail
    assert "xvfb-run" in c.fix and "driver" in c.fix and "--no-images" in c.fix


def test_an_unsafe_cache_folder_is_reported() -> None:
    c = check_with(
        cache=lambda: {
            "path": "/tmp/x",
            "entries": 0,
            "bytes": 0,
            "fallback_reason": "owned by another user",
        }
    )
    assert c.level == "warn" and "owned by another user" in c.detail and "STEPSCRIBE_CACHE" in c.fix


def test_little_memory_and_one_cpu_are_warnings() -> None:
    ram = check_with(free_ram=lambda: 1 * 1024**3)
    assert ram.level == "warn" and "STEPSCRIBE_WORKERS=1" in ram.fix
    unknown = check_with(free_ram=lambda: None)
    assert unknown.level == "ok" and "not reported" in unknown.detail
    cpu = check_with(cpus=lambda: 1)
    assert cpu.level == "warn" and "one process" in cpu.detail


def test_every_problem_comes_with_a_fix() -> None:
    bad = dataclasses.replace(
        healthy(),
        python=lambda: (3, 9, 0),
        occt=lambda: None,
        vtk=lambda: None,
        mcp=lambda: None,
        rendering=lambda: False,
        free_ram=lambda: 100,
        cpus=lambda: 1,
    )
    problems = [c for c in doctor.run_checks(bad) if c.level != "ok"]
    assert len(problems) >= 7 and all(c.fix for c in problems)


def test_the_doctor_command_prints_one_block_per_check_and_sets_the_exit_code(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    runner = CliRunner()
    monkeypatch.setattr(doctor, "default_probe", healthy)
    ok = runner.invoke(app, ["doctor"])
    assert ok.exit_code == 0 and "[ok] Python 3.12.4" in ok.output and "fix:" not in ok.output
    monkeypatch.setattr(
        doctor, "default_probe", lambda: dataclasses.replace(healthy(), occt=lambda: "7.7.2.0")
    )
    bad = runner.invoke(app, ["doctor"])
    assert bad.exit_code == 1 and "[fail] OpenCASCADE" in bad.output
    assert 'fix: python -m pip install -U "cadquery-ocp>=8,<9"' in bad.output
    as_json = runner.invoke(app, ["doctor", "--json"])
    data = json.loads(as_json.output)
    assert {c["name"] for c in data} >= {"Python", "OpenCASCADE", "Rendering"}


def test_the_real_machine_report_runs() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "stepscribe", "doctor"], capture_output=True, text=True, timeout=300
    )
    assert out.returncode in (0, 1), out.stderr[-500:]
    assert "Python" in out.stdout and "OpenCASCADE" in out.stdout and "Cache" in out.stdout


def test_the_agent_skill_calls_the_doctor() -> None:
    from pathlib import Path

    script = Path(__file__).parent.parent / "skills" / "stepscribe" / "scripts" / "check_env.py"
    text = script.read_text(encoding="utf-8")
    assert "doctor" in text and "-m" in text
