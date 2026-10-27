# Robot validation

`stepscribe validate-robot <robot.urdf | pack folder | export folder>` checks a URDF in two layers and reports two separate verdicts.

```
stepscribe validate-robot my_robot_pack
stepscribe validate-robot my_robot_pack --json
stepscribe validate-robot robot.urdf --require-ready     # exit 2 when not simulator ready
stepscribe doctor --robot                                # what is available for the cross-check
```

Exit code: 0 valid, 1 not valid (or the library cross-check found a difference), 2 valid but not simulator ready (only with `--require-ready`).

## Structural validity (layer 1, always, no extra library)

A URDF that parses and is a correct tree. Errors (code `S###`) make the file invalid:

| Check | Codes |
|---|---|
| Reads as XML with a `<robot>` root; no DOCTYPE or entity declarations; under 20 MB | S001, S002 |
| At least one link; unique link and joint names | S010 to S012 |
| Every joint has a parent and a child, and both exist | S013, S014 |
| One parent per link (no closed loop), exactly one root, every link reachable from it (no cycle) | S015 to S018 |
| Joint type known; finite numbers; a non-zero axis; `<limit>` present for revolute and prismatic joints, lower not above upper | S020 to S024 |
| Mesh files exist and stay inside the folder of the URDF (relative paths); absolute, `package://` and URL paths are warned about, not checked | S030 to S034 |
| Inertia (where a link has one): positive mass, symmetric positive-definite matrix, triangle inequality on the principal moments | S040 to S043 |
| With `robot.json` next to the URDF: the same joints, parents, children and kinds (a revolute joint with unknown limits is written `continuous`) | S050 to S054 |

Every name from the file is cleaned (`clean_name`) before it is printed and is a label, never an instruction.

## Simulator readiness (separate)

A valid file can still be rejected by, or behave oddly in, a physics simulator. These findings (`R###`) never change the validity verdict; each says what usually happens and what to change. They describe common simulators in general, not one product's current version.

| Finding | Meaning and fix |
|---|---|
| R001 link with no `<inertial>` (warning; info for a fixed root) | many simulators give the body no mass or refuse a moving body without one: add a mass and inertia |
| R002 continuous joint | limits are unknown, so nothing stops it: set the range and write it as revolute with a limit |
| R003 effort or velocity 0 in a `<limit>` | some simulators read 0 as no force allowed (the joint cannot move), others as no limit: set the real drive values |
| R004 mass at or below 1e-6 kg | unstable simulation: use a realistic mass |
| R005 no `<collision>` geometry | no contact detection, links pass through each other and the floor: write the pack with `--meshes` |
| R006 no `<visual>` geometry (info) | invisible in a viewer |
| R007 masses are estimates (info) | stepscribe masses come from CAD volume and an assumed density |

## Layer 2: cross-check with an optional library

If a robotics library adapter is installed, the URDF is loaded in it and its forward kinematics (link transforms) are compared with stepscribe's own (plain numpy, `stepscribe/robot_check/fk.py`) at the zero pose and at four fixed pseudo-random poses within the limits. A link that differs by more than 1e-6 m or 1e-6 rad is named (`X003`), and a library that rejects the file reports its own words (`X001`).

No library is a dependency of stepscribe, and none is chosen yet. The plug-in structure is in place: an adapter is an object with `name`, `version()`, `load(path)` and `link_transforms(values)` (`stepscribe.robot_check.backends.FkBackend`), registered with `register_backend` or published under the entry-point group `stepscribe.robot_fk`. Without one, layer 1 and the readiness notes still run and the report says how layer 2 will be installed (`pip install 'stepscribe[robot]'`, once the library is chosen). The evaluation of the candidates is kept apart from the code.
