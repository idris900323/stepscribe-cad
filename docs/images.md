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

## Weak-spot overlay (`standard`)

`images/parts/PRT001_weak.png`, per part that a weak spot names: the part in grey with each finding marked in its severity colour (red high, orange medium, yellow low, blue info) and labelled with its ID and the feature it refers to (`W001 H004`). For an edge-distance finding the black line is the measured distance from the hole wall to the nearest face, with its length in mm; it is measured in 3D, so it can look short when it runs along the viewing direction. Findings that name no single part (tipping, interference, floating part) are not drawn.

## Feature highlight (`full`)

`images/parts/PRT001_features.png`, per part with features: an isometric view with a marker at every hole (red ring), cut-out, slot and pocket (blue), boss (orange), fillet (green) and chamfer (purple), each named by its ID, with a colour key. The first 12 fillets and chamfers are marked; a feature on a face turned away from the view is left out and named in the "Not drawn" notes of the index.

## Section view (`full`)

`images/parts/PRT001_section.png`, per part with a hole, cut-out or pocket: the part cut by a plane that runs along the axis of its widest hole (square to the world axis that axis lies furthest from), or across the longest extent when there is no hole. The material on the + side of the plane is removed and the cut face (red) is seen from that side, so wall thickness and the inside show. The plane is named in the title and the caption (`x = 12.00 mm`, part frame). If the cut fails the image is skipped and the index says so.

## Contact map (`standard`, assemblies)

`images/contact_map.png`: the assembly with the parts of the selected contacts in colour and every other part grey, and each contact ID (`C001`, ...) placed where the bounding boxes of its two parts meet (a position estimate; the contact record has no point). Selected: contacts with a touching face or a fit (not near misses or edge touches), largest patch first, at most 12; the caption in `images/INDEX.md` and in the overview lists their IDs, instances, kind and patch area in mm2. A single part has no contact map; the index says so.

## Link colour map (`standard`, robots)

`images/link_map.png`: the assembly coloured by rigid link group (the ground link grey), each part labelled with its link ID and a legend of the link IDs. It is drawn only when the kinematics found joints; otherwise the index says so. Unlike `kinematics_iso.png` (basic), it carries no names and no joint arrows.

## Kinematic diagram and joint axes (`standard`, robots)

`images/kinematic_diagram.png`: a skeleton in the zero pose of the file over a faint outline of the model. Links are bars (from the joint that carries a link to the joints it carries), the base is a square, and each joint is an arrow along its axis labelled with its ID and axis direction (`KJ2 (0.00, 1.00, 0.00)`). `images/kinematic_axes.png`: the joint axes as labelled arrows on the shaded model. Both are drawn only when the kinematics found joints, and carry IDs and numbers only.
