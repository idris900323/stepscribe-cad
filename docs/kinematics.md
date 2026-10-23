# How stepscribe finds links and joints in a robot file

Vendor robot files (an ABB arm, for example) name their solids `<model>_<revision>_LINK3_body2`
and join them with large bores and flange faces rather than screws. This page describes the rules
that read such a file, the numbers they use and how to change them. Every result is a guess
(`Likely:`), carries a confidence and cites its evidence.

## 1. Links from names

A name is searched, case-insensitively and anywhere in it, for `LINK<n>` or `AXIS<n>` (a number),
and otherwise for `BASE`. A prefix such as `IRB1660ID_4-155_IRC5_rev0_` and a suffix such as
`_body2` or `_NB` do not matter. Instance labels that are only assembly-tree occurrence ids
(`NAUO4`) are replaced by the product name before this step.

The names are used only when at least **3 distinct numbered groups** exist and consecutive numbers
touch each other (a contact or a hole stack). Then:

- bodies of one group are one rigid link (confidence 0.8, evidence "name pattern");
- different groups are never merged because they rest on each other, and a hole stack with no
  screw size does not clamp them together.

With no usable names the geometric rules apply unchanged.

## 2. Pivot candidates (bores with no screw size)

A stack of coaxial holes across two or more parts that matches no screw size is a **pivot
candidate**, not a fastener, when it is wide and long:

| Rule | Default | Where to change it |
|---|---|---|
| Smallest diameter | 20 mm | `--pivot-min-diameter`, or `kinematics.pivot.min_diameter_mm` in `stepscribe/knowledge/roles.yaml` |
| Shortest stack | 1 diameter | `--pivot-min-length-ratio`, or `kinematics.pivot.min_length_over_diameter` |

Both limits are inclusive: a Ø20 stack qualifies, and so does one exactly one diameter long.
Smaller or shorter unmatched stacks stay fastener joints with confidence 0 ("needs tapping or an
insert"). A pivot candidate is a revolute joint about the shared hole axis: confidence 0.7 when it
spans two different named links, 0.4 and the wording "pivot or press fit candidate" when there
are no usable names.

## 3. Flange candidates

A planar contact of at least `kinematics.pivot.flange_min_area_mm2` (500 mm²) between two
different named links is a revolute candidate about the contact normal, through the contact
centroid (confidence 0.55). On the same pair:

- a pivot bore that points the same way as the normal raises the confidence and both are cited;
- a bore that disagrees with the normal wins (a perpendicular pivot is the normal case at the
  shoulder and elbow of an arm), the confidence is multiplied by 0.7 and the flange reading is
  listed as the alternative.

## 4. Looking at the decisions

`stepscribe export --debug-kinematics` (also `pack`) writes `data/kinematics_debug.md` and adds a
`kinematics_debug` section to `report.json`. For every contact it lists the kind, area, normal,
centroid, distance, how the pair was classified, the links and why it was merged or kept apart;
for every unmatched hole stack it lists why it is not a fastener and what the model did with it.
