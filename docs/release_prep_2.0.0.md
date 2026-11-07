# Release 2.0.0: preparation notes (nothing is bumped)

The release is **2.0.0**. The bump goes in only on the final release PR (`release/v2` to `main`), together with
the CHANGELOG, README and docs refresh. The report schema stays **0.6.0** and is not tied to the package version.

## Every place that carries the version (checked on `release/v2` at `1791aa4`)

| Site | File and line | Kind |
|---|---|---|
| Package source of truth | `stepscribe/__init__.py:5` `__version__ = "0.1.4"` | edit |
| Built distribution version | `pyproject.toml:7` `dynamic = ["version"]`, `pyproject.toml:43-44` hatch reads `__init__.py` | no number here |
| Plugin | `plugins/stepscribe/.claude-plugin/plugin.json:4` | edit |
| Marketplace entry | `.claude-plugin/marketplace.json:12` | edit |
| Golden report | `tests/golden/plate_4xM3.report.json:4` (`meta.tool_version`) | regenerate |
| Golden Markdown | `tests/golden/two_plates_assembly_FULL.md:6` ("Tool: stepscribe 0.1.4; report schema 0.6.0") | regenerate |
| A stubbed value in a test | `tests/test_doctor.py:19` (`stepscribe=lambda: "0.1.4"`) | fake input, may stay |
| Release check script | `scripts/check_release.py:35-42` compares package, plugin, marketplace entry and the tag | reads, no number |
| Environment check of the skill | `skills/`, `plugins/stepscribe/skills/`, `.github/skills/` `.../scripts/check_env.py:27` | reads the installed metadata, no number |
| MCP server metadata | `stepscribe/mcp/server.py` carries no version string (checked) | none |
| README | install lines (`README.md:16, 60, 85, 121, 192`) name the package, not a version | none |
| Docs | no page names the package version (checked with a search of `docs/`) | none |
| History | `CHANGELOG.md` mentions of older versions | history, not edited |

The goldens are regenerated, not hand-edited: `python -m stepscribe export ...` as the golden tests describe, then
review the diff (only the version string should change).

`tests/test_version_sites.py` fails if the package, the plugin, any marketplace entry or the two goldens disagree.
It does not pin the number, so the bump is one commit that changes the sites above.

## Behaviour changes for the 2.0.0 CHANGELOG entry

See the draft at the top of `CHANGELOG.md` (date left blank for the user to confirm).

## Docs pages to refresh in the release PR

- `docs/images.md` (image sets, time and size, the UI default)
- `docs/kinematics.md`
- `docs/robot_validation.md`
- `docs/step_data.md`
- `docs/mass_distribution.md` (once PR #17 is merged)
- `docs/release_checklist.md`
- `README.md` (feature list, the image sets, the UI, install lines)
- `CHANGELOG.md` (rename "Unreleased", set the date)

## Gates before any tag or PyPI upload

1. macOS green on `release/v2` and on the final release PR head (`docs/release_checklist.md`).
2. `scripts/check_release.py` and `scripts/check_skips.py` pass.
3. The user says go: tag, build and upload are separate approved steps.
