# Several STEP files as one design

Give `stepscribe pack` several files, a folder with `--combine`, or a `.zip`, and you get one combined
assembly and one pack. Each file keeps its own coordinates: **nothing is moved unless you say so.**

## What can be given

| Input | CLI | Web page | MCP tools |
|---|---|---|---|
| Several `.step`/`.stp` files | `stepscribe pack a.step b.step` (add `--combine` for a folder) | pick or drop several | not as a list: zip them |
| A folder | `--combine` (without it, one pack per file) | pick the files | `path=<folder>, combine=true` |
| A `.zip` | `stepscribe pack set.zip` | pick the zip | `path=<zip>` |

Limits (the same everywhere): at most 40 STEP files, 2 GiB in total, 2 GiB unpacked. A zip is checked
before anything is written: paths that leave the folder, absolute paths, drive letters, symbolic
links and too many entries are refused with a plain message.

### MCP: `combine`

Every MCP tool that takes a `path` also takes `combine` (default `false`), and each tool's description
says so. **A folder as `path` is always refused unless `combine=true`**, even when it holds only STEP files
(the flag is your consent that every STEP file under it becomes one assembly); with it, the STEP files under the folder (symbolic links skipped, other files
ignored) are packed into one deterministic zip in the cache and analysed like a zip. The same files give
the same zip bytes and so the same cache key; a changed, added or removed file gives another one. A
single file or a zip is unaffected by the flag. Folders are not accepted by `diff`.

## Two files with one name, or with one content

The rule, exactly. For every pair of input files, compare the **cleaned file name** (case ignored) and the
**sha256 of the bytes**:

| Name | Content | What happens |
|---|---|---|
| same | same | The same file copied into two folders: **one copy is kept**, the later ones are dropped, and the pack says "X is identical to X (same name and sha256): kept one copy". |
| same | different | Both are kept; the later one gets a suffix (`link.step`, `link_2.step`, `link_3.step`), ordered by content hash so the order you list them in never matters. The pack says "two different files are called link.step (sha256 ... and ...): the second is called link_2.step in this pack". |
| different | same | **Both are kept as separate parts**: four identical legs saved as `leg_FL.step`, `leg_FR.step`, `leg_RL.step`, `leg_RR.step` give four parts. Nothing is collapsed and nothing is reported. |
| different | different | Two files, as usual. |

Exception: if `files:` in `design_context.yaml` has an entry for the shared name, two same-name files
with the same content are **both kept** (the entry would otherwise be ambiguous). The first keeps the
name and gets the placement; the second is renamed `link_2.step`, is **not** placed ("as in file")
unless `files:` also has an entry for `link_2.step`, and the pack says so ("two files called link.step
have the same content ...; both are kept because files: gives link.step a placement ...").

Where the pack says it: `00_READ_ME_FIRST.md` (notes under the sources table) and the report warnings.

## Do the files share a frame?

When the files overlap each other as if each was exported around its own origin, or when no two of them
touch or come within 3 mm, the report carries the warning "The N files do not appear to share a
coordinate frame". A set with `files:` placements for every file is not checked (you have said where
they go).

With the warning active, the results that depend on where each file sits say so:

- the top of `00_READ_ME_FIRST.md` has a warning box;
- `01_overview.md` has the full warning, and a one-line hedge over its Kinematics section;
- `02_assembly.md` has the hedge over Relations, Fastener joints and Interferences;
- `05_understanding.md` has it over Kinematics, Load paths and Stability;
- `robot.json` lists it first among its warnings;
- the MCP `get_relations` starts with it, and `get_overview` carries the overview's warning;
- the web page shows a box under the numbers and lists the warning in its Warnings tab.

The hedge is always the same sentence: "The files may not share a coordinate frame; these results may be
meaningless (they depend on where each file sits)." Nothing is withheld: the numbers are still measured
for the positions in the files, and the hedge tells the reader how far to trust them.

Where a part is called a floating part ("no fastener, pivot or joint evidence linking it to the ground
link (it may still touch other parts)"), that means the analysis found no screw, pivot bore or joint
tying it to the ground link. Touching parts without such evidence are listed under Relations and stay
"floating"; this is not a claim that they are separate.

## Placing a file: `files:` in `design_context.yaml`

Placement is a command-line feature: `stepscribe pack a.step b.step --context design_context.yaml`. The web page and the MCP tools take no context file, so there a frame warning can only be answered by running the command line.

```yaml
files:
  link2.step: {offset_mm: [30, 10, 0], rotation_deg: [0, 0, 90]}
```

Convention, for each file:

1. `rotation_deg` is `[rx, ry, rz]` in **degrees**, applied about the **file's own origin** (the point
   `(0, 0, 0)` of that file), as rotations about the **fixed** X, Y and Z axes in that order: first
   about X, then about Y, then about Z. As a matrix: `R = Rz · Ry · Rx`. Positive angles are
   counter-clockwise looking down the axis towards the origin (right-hand rule).
2. `offset_mm` is `[dx, dy, dz]` in **millimetres** and is added **after** the rotation. A point `p` of
   the file ends up at `R · p + offset`.
3. A file named under `files:` is labelled "designer-supplied" in the sources table; the others are
   "as in file". File names are matched ignoring case. A name that matches none of the files is
   reported as a warning ("design_context files: 'x.step' matches none of the files") and changes
   nothing.

Example: a point at `(1, 0, 0)` of a file with `rotation_deg: [90, 0, 90]` and `offset_mm: [5, 6, 7]`
goes to `(5, 7, 7)` (X first leaves it at `(1, 0, 0)`, then Z turns it to `(0, 1, 0)`, then the offset).
Turning about Z first and then X would put it at `(5, 6, 8)`: the order matters, and a test pins it.
