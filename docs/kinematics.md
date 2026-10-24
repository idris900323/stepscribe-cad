# How stepscribe finds links and joints in a robot file

Robot files from manufacturers (an ABB arm, for example) name their solids `<model>_<revision>_LINK3_body2`
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

## 4. The headline and its confidence

A chain of revolute joints from the base is headlined `Likely: N-axis serial arm (confidence X;
evidence KJ1..KJn, L0..Ln)`, followed by the chain facts (links, joints, serial order) and, for six
axes, the layout check: axis 1 vertical; axes 2 and 3 parallel and perpendicular to axis 1; axis 4
perpendicular to axis 3; axis 5 perpendicular to axis 4; axis 6 parallel to axis 4 (within 5
degrees). The confidence is computed in three steps (numbers in `roles.yaml`, `kinematics.arm_headline`):

1. support = 0.50 + 0.065 for every matching check (all six: 0.89);
2. **cap**: support is never above the *weakest joint's confidence + 0.15*, so a matching layout
   cannot make a chain of weak joints look sure (six flange-only joints at 0.55 give at most 0.70);
   when the cap applies the statement says so;
3. each mismatching check then takes 0.08 off, and the mismatch is written out in words.

Axes other than six are not checked and get 0.55, with the same cap. Parts named `LINK<n>` with no
joint evidence are reported as "joint structure not determined", never as a static structure.

## 5. Looking at the decisions

`stepscribe export --debug-kinematics` (also `pack`) writes `data/kinematics_debug.md` and adds a
`kinematics_debug` section to `report.json`. For every contact it lists the kind, area, normal,
centroid, distance, how the pair was classified, the links and why it was merged or kept apart;
for every unmatched hole stack it lists why it is not a fastener and what the model did with it.

## 6. Telling stepscribe what it cannot see

Add a `kinematics:` section to `design_context.yaml`:

```yaml
kinematics:
  base: BASE                  # a link name (BASE, LINK3), a link ID (L0) or a part-name fragment
  joints:
    - between: [LINK1, LINK2] # the two links the joint connects
      type: revolute          # revolute | prismatic | cylindrical
      axis: "+Y"              # +X..-Z or [x, y, z] in the file's frame
      origin: [150, 0, 486.5] # optional, mm; any point on the axis
      range: [-90, 110]       # degrees (revolute) or mm (prismatic)
      positive: cw            # ccw | cw (revolute), "+" | "-" (prismatic)
```

A declared joint replaces the detected one, is marked "Confirmed by designer" and gets confidence 1.0.
A design counts as a robot when it is headlined as a serial arm with at least 3 revolute joints
(`kinematics.arm_headline.robot_min_joints` in `roles.yaml`); a two-joint arm keeps the ordinary
interview. For a robot the interview asks first: which link is the base; whether each joint that rests on a
flange alone really turns about the axis found; which way positive rotation goes; and the range of
the joints, as one question for the whole arm (one line per joint, for example `KJ1: -170 to 170`),
asked only for joints without a `range` in the yaml. The "what drives it" questions come after. Answers are saved under `answers:` and also
mirrored into `kinematics:` (each generated entry has a `source:` list of question IDs, so
`stepscribe answer --undo` removes exactly what the answer wrote; entries you wrote yourself are
never touched).

### Which way is positive

Positive rotation is counter-clockwise looking along the joint's axis arrow toward its origin (the
right-hand rule). For a robot, one question lists every joint's axis arrow as a vector and asks for
one line per joint: `KJ1: ccw` keeps the arrow, `KJ1: cw` reverses it (a slide takes `+` or `-`).
A `cw` joint gets the reversed vector in `robot.json` (`axis_flipped: true`) and in `robot.urdf`,
once, with the evidence "Confirmed by designer: flipped"; the DH-style numbers follow the reversed
arrow. An answer that cannot be read (an unknown joint, a word other than ccw/cw/+/-, an empty
answer) is refused with a message that shows the expected format, and nothing is recorded.

## 7. Joint origins

Each joint origin lies on its axis line. The first joint keeps the point found from the geometry
(the flange centroid, projected onto the axis). Later joints use the foot of the common
perpendicular from the previous joint's axis: for crossing axes that is the intersection, for skew
axes the point of closest approach, and for parallel axes the previous origin projected onto the new
axis. The raw point stays in the data as `evidence_point_mm`.

## 8. robot.json and robot.urdf

For a design with at least one revolute or prismatic joint the pack contains `robot.json` and a
draft `robot.urdf`: link frames (parallel to the file's axes, joints at zero in the stored pose),
joint axes and origins, a DH-style table, and per-link mass, centre of mass and inertia from CAD
volume and a density. All of it is marked as a draft needing human verification:

- masses are estimates, and absent when no material is set (pass `--material`);
- masses of models that are hollow or simplified outer skins are not reliable; bodies with complex or
  free-form geometry (section 9) are listed in the warnings;

- a joint limit is written only when `range` is given in design_context.yaml; otherwise it is
  "unknown" in robot.json. In URDF a revolute joint needs a lower/upper limit (they default to 0,
  which would lock it), so a revolute joint with no known limit is written as `type="continuous"`
  with the comment "limits unknown; change to revolute and add a limit"; one with a designer range
  stays `revolute` with lower, upper, effort 0 and velocity 0 (effort and velocity are not known).
  A prismatic joint has no unlimited form in URDF, so it stays prismatic with a comment;
- lengths in the URDF are metres (a joint at z = 125.7 mm is written 0.1257), masses kilograms,
  inertia kg m^2 and angles radians;
- there is no visual or collision geometry, and the URDF is in metres, kilograms and radians.

## 9. Complex or free-form geometry: no process guess

Cast housings and sculpted skins only *look* printed or moulded, and the process rules would answer
with confidence. For such a part the process reads "unknown", with the evidence
`no process guess: complex or free-form geometry (135 faces, 47% free-form)`: the numbers are what was
measured. A part qualifies when it has **at least 100 faces** and **either**

- it is not a closed solid (the evidence adds ", not a closed solid"), **or**
- **15 % or more** of its faces are free-form (B-spline); the limit is inclusive.

The limits are `complex_geometry` in `stepscribe/knowledge/process_rules.yaml`. A part with fewer
than 100 faces is never affected. A thin or ribbed part made of planes and cylinders is not affected
either, however little of its bounding box it fills: thinness alone does not qualify, and the
real-robot data gave no support for such a trigger.

What changes for such a part:

- the process question skips it, and the summary and part description say there is no guess;
- rules that need a process do not run: the minimum wall rule has a sourced floor per process and
  there is none to apply, so no wall finding is made;
- measured facts are still reported. Edge distance (and the web beside a cut-out) is checked with the
  generic guideline used whenever the process is unknown (1.5 x the hole diameter), and the finding
  says so: "the generic guideline (process unknown) is 1.5 x diameter = 4.5 mm", with the assumption
  "process unknown: the generic guideline (metal factor) is used";
- a process the designer gives in design_context.yaml (`parts: <name>: process: ...`) always wins;
- `robot.json` lists these bodies in its mass warning, using the same rule.

## 10. The other headlines, and the role phrase

Every `Likely:` headline carries a confidence and the IDs it rests on, not only the arm one.

- **General assembly headlines** (mobile base or manipulator, linear slide, single joint, closed
  loop, other mechanism): `Likely: a mobile manipulator, a 4-wheel base (...) carrying a 2-DOF serial
  arm (confidence 0.90; evidence KJ1, KJ2, ..., L0..L7): KJ5 revolute about +X, ...`. The confidence
  is the mean of the joints the headline rests on, never above the weakest of them plus 0.15 (the
  arm headline's cap), and between 0.1 and 0.95. The evidence is those joint IDs and the link IDs.
- **A static structure** (no joint found): `Likely: a static structure with no moving joints
  (confidence 0.60; evidence L0..L4)`. **The 0.60 is a heuristic constant**
  (`kinematics.arm_headline.static_confidence` in `roles.yaml`), not derived from evidence: the claim
  is an absence, so there is nothing to average. Parts named `LINK<n>` get "joint structure not
  determined" instead (section 4).
- **A single part**: `Likely: a single plate (confidence 0.90; evidence PRT001), 60.0 x 60.0 x 5.0
  mm, 4 hole(s), probably a base plate (confidence 0.72).` The first confidence is the shape class's.
- **The role phrase** follows the role's own confidence, rounded to the two decimals shown (so what
  is printed is what is compared): **0.60 or more** reads "probably a <role> (confidence X)",
  **0.30 up to 0.60** reads "possibly a <role> (confidence X)", and **below 0.30 the phrase is left
  out**. The limits are `role_phrase` in `roles.yaml`.
