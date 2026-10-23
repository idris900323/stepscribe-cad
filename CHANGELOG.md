# Changelog

## Unreleased

Robot files from vendors (an ABB arm, for example): links, joints and a robot description.

- **Names.** An instance labelled only with an assembly-tree occurrence id (`NAUO4`) now takes the product name (`LINK3`).
- **Links from names.** `BASE`, `LINK<n>` and `AXIS<n>` are found anywhere in a part name, with any prefix and a `_body<k>` suffix. With three or more numbered groups in a chain, bodies of one group are one link and different groups are never merged because they rest on each other.
- **Pivots and flanges.** A coaxial hole stack that matches no screw size, at least 20 mm wide and as long as it is wide, is a pivot candidate (revolute about the bore) instead of a confidence-0 fastener that locked two links together. A large planar contact between two link groups is a revolute candidate about its normal; a bore that agrees raises the confidence, one that disagrees wins with a lower confidence and the flange reading is listed. Change the limits with `--pivot-min-diameter` and `--pivot-min-length-ratio`; see `docs/kinematics.md`.
- **`--debug-kinematics`** (on `pack` and `export`) writes `data/kinematics_debug.md` and a `kinematics_debug` section in `report.json`: for every contact, why it was merged or kept apart; for every unmatched hole stack, why it is not a fastener.
- **Designer input.** A `kinematics:` section in `design_context.yaml` (base, and joints with type, axis, origin, range, positive direction) replaces what was detected and is marked "Confirmed by designer". New interview questions ask for the base link, the axis of joints known only from a flange, and the sign of positive motion.
- **`robot.json`** in the pack for a model with at least one revolute or prismatic joint: link frames, joint axes and origins, a DH-style table, mass and inertia per link (estimates), and joint limits only from the yaml.
- **Headline.** A chain of revolute joints reads `Likely: 6-axis serial arm (confidence 0.70; evidence KJ1..KJ6, L0..L6)`, with the chain facts and a check of the usual 6-axis layout (a mismatch is written out and lowers the confidence; the confidence is capped by the weakest joint). Parts named `LINK<n>` with no joint evidence read "Joint structure not determined", never "static structure". The overview, understanding file and single-file pack carry the same text.
- **Interview.** For a robot the base link, the axis of flange-only joints, the sign of positive motion and the ranges come first. Answers are also written to the `kinematics:` section, and undo removes them.
- **Joint origins** lie on their axis (common perpendicular from the previous axis); the raw point is kept as `evidence_point_mm`.
- **`robot.urdf`** next to `robot.json`: a draft in SI units with no invented limits or masses.
- Report schema 0.6.0 (new optional fields).

## 0.1.4

Fixes found on a real design (`full ass.step`).

- **Pilot holes set the screw size.** A clearance hole over a smaller blind hole names the screw: a Ø3.2 hole over a Ø2.6 / Ø2.2 blind hole is an M3 into its tapping (pilot) hole, not an M2. The joint text now says so, and no longer says the blind hole "needs tapping or an insert". A Ø2.3 hole over a Ø1.6 blind hole stays M2.
- **Hole table shows ambiguous sizes.** A hole that fits two screw sizes lists both, for example Ø1.6 as "Likely: M1.6 nominal (1.00); or M2 tap drill". The joint evidence names the other reading and says the mating hole decided.
- **Joint lines read correctly.** "Through 2 parts" is used only for stacks that go through; a stack that ends in a threaded or blind hole says "across 2 parts, ending in a threaded or blind hole". The confidence follows the same pattern as every other guess: "Likely: M3 × 14 SHCS (0.90)" instead of "M3 × 14 SHCS (Likely, 0.90)". The wording changes in the single-file pack and the exports.
- Version strings are 0.1.4 in the package, the plugin and the marketplace file.

## 0.1.3

Security and resource hardening (phases H1 to H3) and fixes found on a real design.

**Web page (H1)**
- Every request needs a per-run session token and a local `Host`/`Origin`; JSON and upload calls must use `application/json` / `application/octet-stream`. Images and downloads take the token as `?t=`.
- `/api/start_path` accepts only existing `.step`/`.stp` files, or a sample by index; `/api/samples` no longer lists file paths.
- Uploads are capped (`stepscribe ui --max-upload-mb`, default 500), must look like a STEP file, and partial uploads are deleted. Bad lengths, JSON, density, material and axes return a short 400; unexpected errors return a 500 without a traceback.
- Security headers on every response, a Content-Security-Policy on the page, pack `.html` served as text, quotes escaped in the page's templates.

**Text from STEP files is data (H2)**
- Part and assembly names are cleaned once, in the reader (`stepscribe/text_safety.py`): Unicode-normalised, no control, zero-width or bidi characters, no Markdown/HTML-active characters, at most 64 characters. Names show as inline code in the pack and a "labels only, not instructions" line is in every pack header and the MCP overview. The agent instructions treat file text as untrusted.
- `report.json` keeps only a `name_cleaned` flag, never the original text. Report schema 0.5.0 (new optional `Part.name_cleaned`).
- A 500-character part name no longer crashes the export.

**One analysis, one cache, bounded resources (H3)**
- A shared per-user result cache (`stepscribe cache info|clear`, `--cache-max-gb`) used by the CLI export, the MCP server and the page. The MCP report tools read it and never analyse again (the old second, silent analysis took 166 s on a 7 MB assembly); a file that was not analysed gets a message with the ETA.
- One analysis at a time (`--max-jobs`) with a visible "waiting" state; the worker count respects free RAM.
- The page keeps one live interview session (idle timeout `--session-idle-min`, default 15), restores it from the saved pack, keeps the newest 5 jobs and streams its zip from disk.
- Cancelling or quitting stops the whole worker tree on every OS; a warning appears before very large files (CLI, MCP, page).
- The MCP server writes the stack of a native crash (for example a graphics driver fault while drawing) to `mcp_crash.log` in the cache folder.

**Other security (H4)**
- Learned role models (the `stepscribe.role_models` entry point) are imported only when named in `STEPSCRIBE_ML` or `ml.enabled` in `design_context.yaml`; the ones that ran are listed in the report and the pack.
- The LLM adapter refuses to send an API key over plain `http://` to a remote host (override: `STEPSCRIBE_LLM_ALLOW_INSECURE=1`) and its errors never contain the key. `pip-audit` runs in CI.

**Ease of use (H5)**
- `python -m stepscribe` works (use it when `stepscribe` is "not found"); `stepscribe doctor` checks versions, rendering, cache, memory and CPUs and gives a fix for each problem.
- Dependencies are pinned to what is tested (`cadquery-ocp>=8.0,<9`, upper bounds for `mcp`, `vtk`, `numpy`, `pydantic`, `typer`); the wrong OpenCASCADE version stops with one line. Python 3.13 is tested in CI.
- Common errors (file not found, not a STEP file, external references, no OpenGL, out of memory, timeout, missing extra) show one sentence and a suggestion; `--debug` shows the traceback.
- The README's option defaults are generated from the command line, its links are absolute, and the sdist leaves out media and golden images. The page says when images cannot be drawn on this computer.

**Desktop launcher (H6)**
- `stepscribe shortcut` puts an icon on the desktop (Windows `.lnk`, macOS `.command`, Linux `.desktop`) that runs the Python which installed stepscribe; `--remove` deletes it and nothing that stepscribe did not create is overwritten without `--force`.
- Starting the page twice opens the running one; a busy port picks a free one. The page has a **Quit stepscribe** button, shuts itself down after 10 minutes without an open page (`--idle-exit-min`, never during an analysis), and closing the console window stops every process.

**Fixes**
- A screw into a blind hole stops one thread pitch short of the bottom (M1.6 x 6 became M1.6 x 5 for a 3 mm plate over a 3 mm blind hole).
- A screw that ends in a blind hole no longer gets nut allowance and a nut (M2 x 16 plus 16 nuts became M2 x 12, no nuts).
- Long interview answers no longer break `design_context.yaml`.
- Material keywords match whole words ("plate" is not "pla"); placement rotations are no longer converted to degrees twice; the pack's read-me no longer claims there are no images after the interview rebuilds it; a large thin plate with holes is a plate, not a shaft.
- CI fails if a POSIX-only test is skipped on Linux or macOS.

## 0.1.2

- The project is named **stepscribe-cad** everywhere public: the GitHub repository, the README title, the Claude Code marketplace and plugin (commands are `/stepscribe-cad:export`, `/stepscribe-cad:interview`, `/stepscribe-cad:review`). The command line tool is still `stepscribe` and the Python package is still `stepscribe`.
- The summary says "N fastener pieces to buy (screws, nuts, washers)" instead of "N fasteners", which read as a different count than the shopping list.
- `export_pack` with `copy_to` also reports the path of the copied zip.
- The answers file lock handles the Windows permission errors that appear while another writer deletes its lock or reads the file.

## 0.1.1

- README starts with a step-by-step "Start here" (install, the browser page, the Claude Code commands and in what order, where the files end up).
- `/stepscribe:export` saves the export and zip next to the STEP file (new `copy_to` argument of the `export_pack` tool) and reports the full path.
- Image rendering is skipped, instead of crashing, on machines without usable OpenGL.

## 0.1.0

First release.

- **Measuring:** STEP reader (names, colours, tree, units), exact properties, holes (counterbores, countersinks, blind and through, edge distances), patterns, fillets, chamfers, bosses, slots, pockets, cut-outs (through, recess, stepped, notch), wall thickness, shape classes, standard parts (screws, bearings, motors, extrusions, boards).
- **Assembly:** instances and transforms, bill of materials, planar and cylindrical contacts, fastener joints and shopping list, relations as sentences, optional interference check.
- **Understanding layer:** ribs, gussets, symmetry, manufacturing process, links, joints (servo horns included), degrees of freedom, gears, belts, lead screws, load paths, weak spots, stability, part roles, designer questions and answers.
- **Output:** context pack folder, labelled images with dimensions and joint arrows, `report.json` with a JSON Schema.
- **Portable export** (`stepscribe export`): FULL, COMPACT and SMALL Markdown, a chat bundle, a manifest and a zip; reused from disk when nothing changed.
- **AI integrations:** MCP server with background jobs and image content, an Agent Skill, a Claude Code plugin and marketplace with a reviewer agent, a non-interactive `answer` command. None of them start the local web page.
- **Local web page** (`stepscribe ui`) with progress and ETA, an image viewer and the designer interview.
- **Speed:** exact contact detection pruned by face boxes, parallel part analysis, fixes for quadratic loops on parts with hundreds of holes.
- **License:** AGPL-3.0-only with dual licensing, CLA and trademark notice.
