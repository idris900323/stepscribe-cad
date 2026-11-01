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

With the optional extra installed, MuJoCo does both layer-2 jobs. Its forward kinematics (link transforms) are compared with stepscribe's own (plain numpy, `stepscribe/robot_check/fk.py`) at the zero pose and at four fixed pseudo-random sets of joint values within the limits. A link that differs by more than 1e-6 m or 1e-6 rad is named (`X003`), and a library that rejects the file reports its own words (`X001`). The same MuJoCo also answers the readiness question (below).

Measured on the generated six-axis arm (7 links, 6 joints, 5 poses): the largest difference between MuJoCo and stepscribe is 5.7e-17 m in position and 3.0e-8 rad in rotation. A deliberately flipped axis (the axis of one joint reversed in a copy of the URDF, compared with the kinematics of the original) is detected: 0.355 m and 2.69 rad at the worst link, with `X003` findings naming the links. The zero pose cannot show a reversed axis, which is why the random joint values are part of the check.

```
pip install 'stepscribe[robot]'
```

| Library | Pinned | Used for | Licence (package metadata) |
|---|---|---|---|
| MuJoCo | 3.17.0 | the kinematics cross-check and simulator readiness (`R100` to `R103`) | Apache-2.0 |

No library is a dependency of stepscribe. The extra is MuJoCo only: 8 packages (MuJoCo, absl-py, etils, fsspec, glfw, PyOpenGL, websockets, zipp), about 80 MB installed (the MuJoCo wheel is 16 to 27 MB). Licences read from the installed packages: Apache-2.0 (MuJoCo, absl-py, etils), BSD (fsspec, PyOpenGL, websockets), MIT (glfw, zipp). All are permissive and compatible with stepscribe's AGPL-3.0 and a commercial licence.

**yourdfpy** (MIT) is also supported but is not part of the extra: it requires `trimesh[easy]`, which brings 27 packages and about 225 MB (scipy, embreex and networkx are 84 % of it). If you want an independent second implementation of the kinematics, install it yourself (`pip install yourdfpy`) and run `stepscribe validate-robot <pack> --backend yourdfpy`. Without `--backend`, MuJoCo is used when it is installed, and yourdfpy otherwise.

**macOS on Intel.** MuJoCo publishes no wheel for it (Apple silicon only), so the extra installs nothing there (an environment marker in `pyproject.toml`) and `validate-robot` reports layer 2 as not run, with how to install. Layer 1 and the readiness notes still run.

**Where it is tested.** The CI job `robot` installs the extra and runs every library test on Ubuntu, macOS (the `macos-latest` runner is Apple silicon; no Intel runner is used) and Windows with Python 3.11, 3.12 and 3.13: all nine combinations have a MuJoCo wheel. The library tests are skipped, with the reason "the robot extra is not installed", in the jobs without the extra, and the `robot` job fails if any of them is skipped (`STEPSCRIBE_REQUIRE_ROBOT=1`, see `scripts/check_skips.py`). The one yourdfpy test runs only where yourdfpy is installed and is skipped everywhere else with its own explicit reason. The audit (`pip-audit`) runs in the `robot` job as a warning, like the audit of the main job; on the day of the check it found nothing in the extra or its packages (only the old `pip` of a fresh virtual environment, which the job upgrades first).

**How MuJoCo's readiness answer is reported.** It is a readiness finding, never a validity finding: `R100` (info) says it compiled the file; `R101` (error) says it refused it and quotes the library's reason (cleaned); `R102` notes that continuous joints become hinges with no range; `R103` notes that a URDF carries no actuators. A file MuJoCo refuses is therefore NOT READY but can still be VALID. The measured behaviour that led to the choice (a link with no inertia is refused or given an invented mass; a missing mesh file is a hard error) is in the evaluation kept with the project notes.

The plug-in structure is unchanged: an adapter is an object with `name`, `version()`, `load(path)` and `link_transforms(values)` (`stepscribe.robot_check.backends.FkBackend`), registered with `register_backend` or published under the entry-point group `stepscribe.robot_fk`. Without a library, layer 1 and the readiness notes still run and the report says how to install the extra.
