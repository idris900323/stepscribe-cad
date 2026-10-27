# Images

`pack` and `export` take `--images none | basic | standard | full` (default `basic`; `--no-images` still works and means `none`).

| Set | What a pack gets |
|---|---|
| `none` | no images |
| `basic` | exactly the images of earlier versions: assembly iso, front, top and exploded views, the kinematics view of a robot, and an iso and an axis view per part |
| `standard` | basic, plus the types below that are marked standard |
| `full` | standard, plus the types marked full |

The default stays `basic`, so default packs, their size and their run time do not change. The extra images have at most `--image-max-side` pixels on their longest side (default 1200) and at most 20 parts get a per-part image of each type (60 extra images in all), so AI vision input stays small. Rendering is offscreen and deterministic: the same input gives the same file names and label positions.

Every label drawn on an extra image is an ID (`PRT`, `H`, `P`, `W`, ...) or a number, never a name from the file: a name drawn into an image would be a way to put instructions into it. `images/INDEX.md` lists each extra image with what it shows, the IDs on it and the text section it pairs with, and the same caption stands next to the image reference in the part Markdown, written as plain facts so an AI that cannot see images can use it. An image type that cannot be drawn for a part (no holes, too many faces, an error) is skipped and named in the "Not drawn" section of the index; it never stops the pack. The read-me names the image set when it is not `basic`.

## Hole map (`standard`)

`images/parts/PRT001_holes.png`, per part with holes: the part seen along its main hole axis, every hole circled (red through, blue blind) and labelled with its ID and diameter in mm (`H003 dia 5.1`), plus the pattern ID where the hole belongs to a recognised pattern (`P001`). At most 40 holes are labelled; the rest stay in the hole table.

## Three-view drawing (`standard`)

`images/parts/PRT001_views.png`, per part: front, top and right orthographic views on one sheet with the overall width and height of each view drawn as dimension lines in mm (where the view is large enough to hold them) and the overall size written in the fourth cell.
