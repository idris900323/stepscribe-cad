# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""The two library adapters behind ``pip install 'stepscribe[robot]'``.

* **yourdfpy** (MIT) is an independent implementation of URDF kinematics. It is the default for the
  forward-kinematics cross-check (:class:`YourdfpyBackend`).
* **MuJoCo** (Apache-2.0) compiles the URDF into a physical model and refuses what a physics engine
  cannot use. :func:`mujoco_readiness` turns that answer into readiness findings; the adapter
  :class:`MujocoBackend` can also serve as a kinematics backend (``--backend mujoco``).

Neither library is imported until an adapter is created: the factories raise ImportError when the
library is missing, and the registry then leaves that adapter out. Everything a library says about
a file is a label (cleaned), never an instruction.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from pathlib import Path
from typing import Any

import numpy as np

from stepscribe.robot_check.findings import Finding
from stepscribe.robot_check.model import MOVING, parse_urdf
from stepscribe.text_safety import clean_name

MAX_MESSAGE = 300


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


class YourdfpyBackend:
    """Forward kinematics from yourdfpy; meshes are not loaded (the cross-check is about frames)."""

    name = "yourdfpy"

    def __init__(self) -> None:
        # import_module: ImportError when the library is missing, and no stubs are needed
        self._module: Any = importlib.import_module("yourdfpy")
        self._robot: Any = None
        self._joints: list[str] = []

    def version(self) -> str:
        return _version("yourdfpy")

    def load(self, urdf_path: Path) -> None:
        self._robot = self._module.URDF.load(
            str(urdf_path),
            build_scene_graph=True,
            load_meshes=False,
            load_collision_meshes=False,
        )
        self._joints = list(self._robot.actuated_joint_names)

    def link_transforms(self, values: dict[str, float]) -> dict[str, np.ndarray]:
        robot = self._robot
        robot.update_cfg(np.array([values.get(j, 0.0) for j in self._joints], dtype=float))
        base = robot.base_link
        return {
            link: np.array(robot.get_transform(frame_to=link, frame_from=base), dtype=float)
            for link in robot.link_map
        }


class MujocoBackend:
    """Forward kinematics from MuJoCo's compiled model (bodies are the URDF links)."""

    name = "mujoco"

    def __init__(self) -> None:
        self._mj: Any = importlib.import_module("mujoco")
        self._model: Any = None
        self._data: Any = None
        self._links: list[str] = []
        self._root: str = ""

    def version(self) -> str:
        return _version("mujoco")

    def load(self, urdf_path: Path) -> None:
        urdf = parse_urdf(urdf_path.read_text(encoding="utf-8", errors="replace"))
        children = {j.child for j in urdf.joints}
        self._links = sorted(link.name for link in urdf.links)
        self._root = next((name for name in self._links if name not in children), "")
        self._model = self._mj.MjModel.from_xml_path(str(urdf_path))
        self._data = self._mj.MjData(self._model)

    def link_transforms(self, values: dict[str, float]) -> dict[str, np.ndarray]:
        mj, model, data = self._mj, self._model, self._data
        mj.mj_resetData(model, data)
        for joint, value in values.items():
            jid = mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, joint)
            if jid >= 0:
                data.qpos[model.jnt_qposadr[jid]] = value
        mj.mj_kinematics(model, data)
        out: dict[str, np.ndarray] = {}
        for link in self._links:
            bid = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, link)
            if bid < 0:
                if link == self._root:  # a static root link is merged into the world body
                    out[link] = np.eye(4)
                continue
            t = np.eye(4)
            t[:3, :3] = np.array(data.xmat[bid], dtype=float).reshape(3, 3)
            t[:3, 3] = np.array(data.xpos[bid], dtype=float)
            out[link] = t
        return out


def mujoco_readiness(urdf_path: Path) -> list[Finding]:
    """What MuJoCo says about the URDF as a physical model, as readiness findings (R1xx).

    Raises ImportError when MuJoCo is not installed. A rejection is an error finding with the
    library's own reason; a model that compiles is one info finding that says so.
    """
    mujoco: Any = importlib.import_module("mujoco")
    version = _version("mujoco")
    try:
        model = mujoco.MjModel.from_xml_path(str(urdf_path))
    except Exception as exc:  # noqa: BLE001 - the library's reason for refusing is the finding
        why = clean_name(f"{type(exc).__name__}: {exc}")[:MAX_MESSAGE]
        return [
            Finding(
                "R101",
                "error",
                f"MuJoCo {version} does not accept this file as a physical model: {why}",
                "Fix what MuJoCo names (usually a mass, an inertia or a missing mesh), then validate again.",
            )
        ]
    findings = [
        Finding(
            "R100",
            "info",
            f"MuJoCo {version} compiles the file: {model.nbody - 1} bodies, {model.njnt} joints, "
            f"{model.ngeom} geometries.",
        )
    ]
    urdf = parse_urdf(urdf_path.read_text(encoding="utf-8", errors="replace"))
    unlimited = [j.name for j in urdf.joints if j.type == "continuous"]
    if unlimited:
        findings.append(
            Finding(
                "R102",
                "info",
                f"MuJoCo reads {len(unlimited)} continuous joint(s) as hinges with no range.",
                "Give them a range if the real joint has one.",
            )
        )
    moving = [j for j in urdf.joints if j.type in MOVING]
    if moving and not model.nu:
        findings.append(
            Finding(
                "R103",
                "info",
                "The model has no actuators: MuJoCo needs them added before it can drive a joint.",
                "Add actuators in the simulator scene; a URDF does not carry them.",
            )
        )
    return findings
