"""Every place that carries the version says the same thing. The number itself is not pinned here:
a release changes it in one commit, and this test fails if any site was missed."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collect_sites(root: Path = ROOT) -> dict[str, str]:
    """Version of every site, by name. A site that cannot be read is an error, not a skip."""
    sites: dict[str, str] = {}
    init = (root / "stepscribe" / "__init__.py").read_text("utf-8")
    sites["stepscribe/__init__.py __version__"] = re.search(
        r'__version__\s*=\s*"([^"]+)"', init
    ).group(1)  # type: ignore[union-attr]
    plugin = json.loads((root / "plugins/stepscribe/.claude-plugin/plugin.json").read_text("utf-8"))
    sites["plugins/stepscribe/.claude-plugin/plugin.json"] = plugin["version"]
    market = json.loads((root / ".claude-plugin/marketplace.json").read_text("utf-8"))
    for entry in market["plugins"]:
        sites[f".claude-plugin/marketplace.json: {entry['name']}"] = entry["version"]
    golden = json.loads((root / "tests/golden/plate_4xM3.report.json").read_text("utf-8"))
    sites["tests/golden/plate_4xM3.report.json meta.tool_version"] = golden["meta"]["tool_version"]
    text = (root / "tests/golden/two_plates_assembly_FULL.md").read_text("utf-8")
    sites["tests/golden/two_plates_assembly_FULL.md 'Tool: stepscribe'"] = re.search(
        r"Tool: stepscribe (\S+?);", text
    ).group(1)  # type: ignore[union-attr]
    return sites


def disagreements(sites: dict[str, str]) -> list[str]:
    values = set(sites.values())
    return [] if len(values) <= 1 else [f"{k}: {v}" for k, v in sorted(sites.items())]


def test_every_site_that_carries_the_version_agrees() -> None:
    sites = collect_sites()
    assert len(sites) >= 5, sites  # the collector must not quietly find nothing
    for expected in ("__version__", "plugin.json", "marketplace.json", "report.json", "FULL.md"):
        assert any(expected in name for name in sites), expected
    assert disagreements(sites) == [], disagreements(sites)


def test_the_package_version_comes_from_one_place_in_pyproject() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert "version" in project["project"].get("dynamic", []), (
        "pyproject must not carry its own number"
    )
    assert project["tool"]["hatch"]["version"]["path"] == "stepscribe/__init__.py"


def test_two_sites_that_disagree_are_caught() -> None:
    sites = collect_sites()
    broken = {**sites, "plugins/stepscribe/.claude-plugin/plugin.json": "9.9.9"}
    assert disagreements(broken), "a mismatch must be reported"
    assert "plugins/stepscribe/.claude-plugin/plugin.json: 9.9.9" in disagreements(broken)
    assert disagreements({"a": "1.0.0", "b": "1.0.0"}) == []


def test_the_installed_package_reports_the_same_version_as_the_source() -> None:
    import stepscribe

    assert stepscribe.__version__ == collect_sites()["stepscribe/__init__.py __version__"]


def test_the_version_flag_prints_only_the_package_version() -> None:
    from typer.testing import CliRunner

    from stepscribe import __version__
    from stepscribe.cli import app

    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0 and result.output.strip() == __version__


def test_the_built_wheel_ships_the_json_schema_unchanged(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import zipfile

    import hatchling.build

    root = Path(__file__).resolve().parent.parent
    monkeypatch.chdir(root)
    name = hatchling.build.build_wheel(str(tmp_path))
    with zipfile.ZipFile(tmp_path / name) as zf:
        shipped = zf.read("stepscribe/schema/report.schema.json")
    assert shipped == (root / "schema" / "report.schema.json").read_bytes()
    from stepscribe.exporter import json_schema

    assert json.loads(shipped) == json_schema()  # still the schema the code produces (0.6.0)
