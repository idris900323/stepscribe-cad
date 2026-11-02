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

Every MCP tool that takes a `path` also takes `combine` (default `false`). A folder as `path` is refused
unless `combine=true`; with it, the STEP files under the folder (symbolic links skipped, other files
ignored) are packed into one deterministic zip in the cache and analysed like a zip. The same files give
the same zip bytes and so the same cache key; a changed, added or removed file gives another one. A
single file or a zip is unaffected by the flag. Folders are not accepted by `diff`.

## Two files with one name

Different files that end up with the same cleaned name (for example `left/link.step` and
`right/link.step` in a zip) are **not merged and not dropped**. They are ordered by name and then by
content hash, so the order you give them in never matters, and the later ones get a suffix: `link.step`,
`link_2.step`. The pack says so in `00_READ_ME_FIRST.md` (and in the report warnings): "two different
files are called link.step (sha256 ... and ...): the second is called link_2.step in this pack". Two
files with the same bytes are the same file: one copy is kept, and the pack says that too.

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
