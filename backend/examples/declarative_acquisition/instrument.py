"""A microscope described by what it is, planning what it has to do.

Ask for an image at a place, in any coordinate system with a route to the stage::

    instrument = Instrument.load("microscope.yaml", routines=simulated.ROUTINES)
    plan = instrument.plan(Request(Position("plate-1", x=9000.0, y=9000.0), channel="gfp"))
    print(plan.describe())
    record = instrument.apply(plan)

The plan says what moves, by how much, and which calibrations are good, stale or missing, before
anything moves. Three ideas carry it:

- **One graph.** Pixels, the stage, a well plate and the motors are coordinate systems, and what
  connects them are edges, as in mikro and OME-Zarr RFC-5. "Go there" is walking that graph to
  the motors. An earlier image is a system too, so a point picked in it is a place to go.
- **What impacts what is declared per calibration.** A variable either *selects* which calibration
  applies or is *used* by it; time, events and the calibrations it depends on make it stale.
- **Nothing here runs a microscope.** It is a self-contained example of the model: the routines and
  the camera are passed in (`simulated`), and the runtime does not import it.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

import numpy as np
import yaml

Matrix = np.ndarray


class Validity(IntEnum):
    """How far a transformation is known, in mikro's words (`PlacementValidity`).

    The order is this example's: mikro takes a layer's validity from its weakest edge.
    """

    UNKNOWN = 0
    INFERRED = 1  # from nominal values: the pixel pitch through the magnification
    MANUAL = 2  # measured, and not checked since
    VALIDATED = 3  # measured, and a check confirmed it


class DescriptionError(ValueError):
    """The description of the microscope contradicts itself."""


class NoRoute(ValueError):
    """Two coordinate systems are not connected."""


class Blocked(RuntimeError):
    """A plan was applied although something it needs refuses to start."""


def translation(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Matrix:
    """A 4x4 translation over (x, y, z)."""
    matrix = np.eye(4)
    matrix[:3, 3] = (x, y, z)
    return matrix


def scaling(x: float = 1.0, y: float = 1.0, z: float = 1.0) -> Matrix:
    """A 4x4 scaling over (x, y, z)."""
    return np.diag([x, y, z, 1.0])


def _digest(payload: Any) -> str:  # noqa: ANN401 - anything JSON can say
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.blake2b(encoded, digest_size=6).hexdigest()


@dataclass(frozen=True)
class Edge:
    """A map from one coordinate system to another, and how far it is known."""

    source: str
    target: str
    matrix: Matrix
    validity: Validity
    name: str = ""


class CoordinateGraph:
    """Coordinate systems are nodes, transformations are edges; a route may walk one backwards."""

    def __init__(self, edges: tuple[Edge, ...] | list[Edge] = ()) -> None:
        """A graph of `edges`."""
        self.edges: list[Edge] = list(edges)

    def route(self, source: str, target: str) -> list[tuple[Edge, bool]]:
        """The edges from `source` to `target`, each with whether it is walked forwards.

        Raises:
            NoRoute: They are not connected.
        """
        queue: deque[tuple[str, list[tuple[Edge, bool]]]] = deque([(source, [])])
        seen = {source}
        while queue:
            at, walked = queue.popleft()
            if at == target:
                return walked
            for edge in self.edges:
                for start, end, forwards in (
                    (edge.source, edge.target, True),
                    (edge.target, edge.source, False),
                ):
                    if start == at and end not in seen:
                        seen.add(end)
                        queue.append((end, [*walked, (edge, forwards)]))
        raise NoRoute(f"no route from {source!r} to {target!r}")

    def matrix(self, source: str, target: str) -> Matrix:
        """The map from `source` to `target`, composed along the route."""
        matrix = np.eye(4)
        for edge, forwards in self.route(source, target):
            matrix = (edge.matrix if forwards else np.linalg.inv(edge.matrix)) @ matrix
        return matrix

    def transform(self, point: tuple[float, float, float], source: str, target: str) -> np.ndarray:
        """`point` (x, y, z) in `source`, said in `target`."""
        return (self.matrix(source, target) @ np.array([*point, 1.0]))[:3]

    def validity(self, source: str, target: str) -> Validity:
        """How far the route is known: as far as its weakest edge."""
        known = [edge.validity for edge, _ in self.route(source, target)]
        return min(known, default=Validity.VALIDATED)


@dataclass(frozen=True)
class Variable:
    """A value of the instrument, set by an actuator when it has one."""

    name: str  # "objective.slot"
    initial: Any
    actuator: str | None = None
    axis: str | None = None
    steps_per_um: float | None = None
    inverted: bool = False
    unit: str | None = None
    values: Mapping[Any, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Impact:
    """How the variables of a cube impact one quantity."""

    selects: tuple[str, ...] = ()
    uses: tuple[str, ...] = ()


@dataclass(frozen=True)
class Cube:
    """A part of the microscope: what it is, and what its variables impact."""

    name: str
    kind: str
    variables: Mapping[str, Variable]
    impacts: Mapping[str, Impact]
    properties: Mapping[str, Any]


@dataclass(frozen=True)
class LightPath:
    """How light connects the cubes. The role of a cube belongs here, not to the cube."""

    name: str
    illumination: tuple[str, ...]
    detection: tuple[str, ...]

    @property
    def cubes(self) -> tuple[str, ...]:
        """Every cube on the path, once."""
        return tuple(dict.fromkeys((*self.illumination, *self.detection)))


@dataclass(frozen=True)
class Channel:
    """A light path and what has to be set to use it."""

    name: str
    path: str
    settings: Mapping[str, Any]


@dataclass(frozen=True)
class Calibration:
    """How a quantity is obtained, and what makes it stale."""

    quantity: str
    routine: str
    on_stale: str = "warn"
    timeout_h: float | None = None
    invalidated_by: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    nominal: bool = False


@dataclass(frozen=True)
class Entry:
    """A measured value of a quantity, for one key."""

    value: Any
    validity: Validity
    measured_at: float
    version: int
    dependencies: Mapping[str, int]


@dataclass(frozen=True)
class Status:
    """Whether a quantity can be relied on right now."""

    code: str  # ok | missing | expired | invalidated | dependency
    reason: str = ""

    @property
    def ok(self) -> bool:
        """Whether it can be relied on."""
        return self.code == "ok"


@dataclass(frozen=True)
class Position:
    """A place, in a coordinate system. No `z` asks the focus plane for it."""

    system: str
    x: float
    y: float
    z: float | None = None
    z_offset: float = 0.0


@dataclass(frozen=True)
class Request:
    """One image: where, through which channel, with which settings on top of it."""

    at: Position
    channel: str
    settings: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Acquisition:
    """A multidimensional acquisition: it is nothing but the requests it expands into."""

    positions: tuple[Position, ...]
    channels: tuple[str, ...]
    z_offsets: tuple[float, ...] = (0.0,)
    timepoints: int = 1
    settings: Mapping[str, Any] = field(default_factory=dict)

    def requests(self) -> Iterator[Request]:
        """One request per image: per timepoint, per position, per plane, per channel."""
        for _ in range(self.timepoints):
            for position in self.positions:
                for z_offset in self.z_offsets:
                    for channel in self.channels:
                        at = Position(position.system, position.x, position.y, position.z, z_offset)
                        yield Request(at, channel, self.settings)


@dataclass(frozen=True)
class Setpoint:
    """A variable to change, and what its actuator is told."""

    variable: str
    current: Any
    target: Any
    actuator: str | None = None
    native: Any = None


@dataclass(frozen=True)
class Need:
    """A calibration a request depends on, and what is done about it."""

    quantity: str
    key: str
    status: Status
    action: str  # ok | nominal | repair | warn | block


@dataclass
class Plan:
    """What applying a request does, in order. Nothing has moved yet."""

    request: Request
    path: str
    target: dict[str, float] = field(default_factory=dict)
    route: list[str] = field(default_factory=list)
    before: list[Setpoint] = field(default_factory=list)
    moves: list[Setpoint] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    z: Setpoint | None = None
    z_after_repairs: bool = False
    after: list[Setpoint] = field(default_factory=list)
    needs: list[Need] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    def describe(self) -> str:
        """The plan, for a person to read."""
        at = self.request.at
        lines = [f"acquire {self.request.channel!r} at {at.system} ({at.x:g}, {at.y:g})"]
        if self.route:
            lines.append("  route   " + " -> ".join(self.route))
        steps = [*self.before, *self.moves]
        for step in steps:
            lines.append(f"  set     {_describe_setpoint(step)}")
        for quantity in self.repairs:
            lines.append(f"  repair  {quantity}")
        if self.z is not None:
            lines.append(f"  set     {_describe_setpoint(self.z)}")
        elif self.z_after_repairs:
            lines.append("  set     sample-stage.z from focus_plane, once repaired")
        for step in self.after:
            lines.append(f"  set     {_describe_setpoint(step)}")
        for need in self.needs:
            reason = f" ({need.status.reason})" if need.status.reason else ""
            lines.append(f"  needs   {need.quantity}[{need.key}] {need.action}{reason}")
        lines.extend(f"  BLOCKED {reason}" for reason in self.blocked)
        return "\n".join(lines)


def _describe_setpoint(step: Setpoint) -> str:
    native = f"  [{step.actuator} = {step.native:g}]" if step.actuator else ""
    current = f"{step.current:g}" if isinstance(step.current, float) else step.current
    target = f"{step.target:g}" if isinstance(step.target, float) else step.target
    return f"{step.variable}: {current} -> {target}{native}"


@dataclass(frozen=True)
class Record:
    """What was true when an image was taken: the light path as the metadata hub.

    Every instrument fact about the image comes from here, and it is written out into mikro's
    `CoordinateAnchor` spokes and one registration edge (`mikro_export`).
    """

    image: str  # the coordinate system of the image
    channel: str
    path: str
    matrix: Matrix  # pixels to stage, position included
    validity: Validity
    edge_name: str
    stage: Mapping[str, float]
    values: Mapping[str, Any]
    calibrations: Mapping[str, Need]
    acquired_at: float
    frame: np.ndarray


#: A routine measures a quantity: it gets the instrument and the state it measures under.
Routine = Callable[["Instrument", str, Mapping[str, Any]], tuple[Any, Validity]]


class Instrument:
    """The description of a microscope, its current values and its calibrations."""

    def __init__(
        self,
        description: Mapping[str, Any],
        routines: Mapping[str, Routine],
        camera: Callable[[Instrument, int, int], np.ndarray],
        clock: Callable[[], float] = time.time,
    ) -> None:
        """An instrument at the initial values of `description`, with nothing calibrated."""
        self.name: str = description["microscope"]
        self.systems: Mapping[str, Mapping[str, Any]] = description["systems"]
        self.cubes = {
            name: _cube(name, spec) for name, spec in (description.get("cubes") or {}).items()
        }
        self.paths = {
            name: LightPath(name, tuple(spec["illumination"]), tuple(spec["detection"]))
            for name, spec in (description.get("paths") or {}).items()
        }
        self.channels = {
            name: Channel(name, spec["path"], spec.get("set") or {})
            for name, spec in (description.get("channels") or {}).items()
        }
        self.rules: list[Mapping[str, Any]] = description.get("rules") or []
        self.calibrations = {
            name: Calibration(
                quantity=name,
                routine=spec["routine"],
                on_stale=spec.get("on_stale", "warn"),
                timeout_h=spec.get("timeout_h"),
                invalidated_by=tuple(spec.get("invalidated_by") or ()),
                depends_on=tuple(spec.get("depends_on") or ()),
                nominal=bool(spec.get("nominal", False)),
            )
            for name, spec in (description.get("calibrations") or {}).items()
        }
        self.routines = routines
        self.camera = camera
        self.clock = clock
        self.variables = {
            variable.name: variable
            for cube in self.cubes.values()
            for variable in cube.variables.values()
        }
        self.values: dict[str, Any] = {
            name: variable.initial for name, variable in self.variables.items()
        }
        self.motors: dict[str, Any] = {}
        self.log: list[str] = []
        self.images: list[Edge] = []
        self._entries: dict[tuple[str, str], Entry] = {}
        self._events: dict[str, float] = {}
        self._validate()

    @classmethod
    def load(
        cls,
        path: str | Path,
        routines: Mapping[str, Routine],
        camera: Callable[[Instrument, int, int], np.ndarray],
        clock: Callable[[], float] = time.time,
    ) -> Instrument:
        """The instrument the file at `path` describes."""
        return cls(yaml.safe_load(Path(path).read_text()), routines, camera, clock)

    def _validate(self) -> None:
        """Refuse a description whose parts name what does not exist."""
        problems: list[str] = []
        for cube in self.cubes.values():
            for quantity, impact in cube.impacts.items():
                for variable in (*impact.selects, *impact.uses):
                    if variable not in cube.variables:
                        problems.append(f"{cube.name}: {quantity} names no variable {variable!r}")
        for path in self.paths.values():
            problems.extend(
                f"path {path.name}: no cube {name!r}"
                for name in path.cubes
                if name not in self.cubes
            )
        for channel in self.channels.values():
            if channel.path not in self.paths:
                problems.append(f"channel {channel.name}: no path {channel.path!r}")
            problems.extend(
                f"channel {channel.name}: no variable {name!r}"
                for name in channel.settings
                if name not in self.variables
            )
        for rule in self.rules:
            problems.extend(
                f"rule: no variable {name!r}"
                for name in (rule["moving"], *rule["require"])
                if name not in self.variables
            )
        for calibration in self.calibrations.values():
            if calibration.routine not in self.routines:
                problems.append(f"{calibration.quantity}: no routine {calibration.routine!r}")
            problems.extend(
                f"{calibration.quantity}: depends on unknown {name!r}"
                for name in calibration.depends_on
                if name not in self.calibrations
            )
            if calibration.on_stale not in ("repair", "warn", "block"):
                problems.append(f"{calibration.quantity}: on_stale {calibration.on_stale!r}")
        for name, system in self.systems.items():
            registered_by = system.get("registered_by")
            if registered_by and registered_by not in self.calibrations:
                problems.append(f"system {name}: no calibration {registered_by!r}")
        problems.extend(self._cycles())
        if problems:
            raise DescriptionError("; ".join(problems))

    def _cycles(self) -> list[str]:
        """Calibrations that end up depending on themselves."""

        def reaches(start: str, name: str, seen: set[str]) -> bool:
            calibration = self.calibrations.get(name)
            for dependency in calibration.depends_on if calibration else ():
                if dependency == start:
                    return True
                if dependency not in seen:
                    seen.add(dependency)
                    if reaches(start, dependency, seen):
                        return True
            return False

        return [
            f"{name}: depends on itself" for name in self.calibrations if reaches(name, name, set())
        ]

    # --- what impacts what

    def impact_report(self) -> list[dict[str, Any]]:
        """Which variable matters for what, on which paths: derived, never declared.

        A cube is reused across designs and cannot know a path's name. It says what its variables
        impact, a path says which cubes it holds, and this follows.
        """
        rows = []
        for cube in self.cubes.values():
            paths = sorted(p.name for p in self.paths.values() if cube.name in p.cubes)
            for quantity, impact in cube.impacts.items():
                for relation, names in (("selects", impact.selects), ("uses", impact.uses)):
                    for name in names:
                        variable = cube.variables[name]
                        rows.append(
                            {
                                "variable": variable.name,
                                "actuator": variable.actuator,
                                "relation": relation,
                                "quantity": quantity,
                                "paths": paths,
                            }
                        )
        return rows

    def quantities(self, path: LightPath) -> list[str]:
        """The calibrated quantities the cubes of `path` impact."""
        found = {
            quantity
            for name in path.cubes
            for quantity in self.cubes[name].impacts
            if quantity in self.calibrations
        }
        return sorted(found)

    def key(self, quantity: str, path: LightPath, state: Mapping[str, Any]) -> str:
        """Which calibration of `quantity` applies: the values of what selects it on `path`."""
        selected = {
            self.cubes[name].variables[variable].name: state[
                self.cubes[name].variables[variable].name
            ]
            for name in path.cubes
            for variable in (
                self.cubes[name].impacts[quantity].selects
                if quantity in self.cubes[name].impacts
                else ()
            )
        }
        return _digest({"quantity": quantity, "selected": selected})

    def status(self, quantity: str, path: LightPath, state: Mapping[str, Any]) -> Status:
        """Whether `quantity` can be relied on under `state`.

        Unknown counts as out of spec, and nothing is in spec while what it depends on is not: the
        rules of Optimus (Kelly et al., "Physical qubit calibration on a directed acyclic graph").
        """
        calibration = self.calibrations[quantity]
        entry = self._entries.get((quantity, self.key(quantity, path, state)))
        if entry is None:
            return Status("missing", "never measured for this setup")
        age_h = (self.clock() - entry.measured_at) / 3600.0
        if calibration.timeout_h is not None and age_h > calibration.timeout_h:
            return Status(
                "expired", f"measured {age_h:.0f} h ago, holds {calibration.timeout_h:g} h"
            )
        for event in calibration.invalidated_by:
            if self._events.get(event, float("-inf")) > entry.measured_at:
                return Status("invalidated", f"{event} since it was measured")
        for dependency in calibration.depends_on:
            below = self.status(dependency, path, state)
            nominal = below.code == "missing" and self.calibrations[dependency].nominal
            if not below.ok and not nominal:
                return Status("dependency", f"{dependency} is {below.code}")
            known = self._entries.get((dependency, self.key(dependency, path, state)))
            if (known.version if known else 0) != entry.dependencies.get(dependency, 0):
                return Status("dependency", f"{dependency} was recalibrated since")
        return Status("ok")

    def event(self, name: str) -> None:
        """Something happened that some calibrations do not survive."""
        self._events[name] = self.clock()

    # --- calibrating

    def calibrate(self, quantity: str, path: str) -> Entry:
        """Run the routine of `quantity` under the current values and keep what it measures."""
        calibration = self.calibrations[quantity]
        light_path = self.paths[path]
        value, validity = self.routines[calibration.routine](self, quantity, self.values)
        key = self.key(quantity, light_path, self.values)
        previous = self._entries.get((quantity, key))
        dependencies = {}
        for dependency in calibration.depends_on:
            known = self._entries.get((dependency, self.key(dependency, light_path, self.values)))
            dependencies[dependency] = known.version if known else 0
        entry = Entry(
            value=value,
            validity=validity,
            measured_at=self.clock(),
            version=(previous.version if previous else 0) + 1,
            dependencies=dependencies,
        )
        self._entries[(quantity, key)] = entry
        self.log.append(f"calibrate {quantity}")
        return entry

    def confirm(self, quantity: str, path: str) -> Entry:
        """A check found the value still right: it holds for longer, and is now VALIDATED.

        The value did not change, so what depends on it stays valid: only `calibrate` does that.
        """
        key = self.key(quantity, self.paths[path], self.values)
        entry = self._entries[(quantity, key)]
        confirmed = Entry(
            entry.value, Validity.VALIDATED, self.clock(), entry.version, entry.dependencies
        )
        self._entries[(quantity, key)] = confirmed
        return confirmed

    def entry(self, quantity: str, path: LightPath, state: Mapping[str, Any]) -> Entry | None:
        """The measured value of `quantity` under `state`, good or stale."""
        return self._entries.get((quantity, self.key(quantity, path, state)))

    # --- the graph

    def graph(self, path: LightPath, state: Mapping[str, Any]) -> CoordinateGraph:
        """The coordinate graph as it holds under `state`.

        Only a registration that can be relied on gives a system its route to the stage, so a
        position cannot be reached through one that went stale.
        """
        edges = [Edge("stage", "motors", self._motor_matrix(), Validity.MANUAL, "steps_per_um")]
        edges.extend(self.images)
        for name, system in self.systems.items():
            registered_by = system.get("registered_by")
            if registered_by and self.status(registered_by, path, state).ok:
                entry = self.entry(registered_by, path, state)
                assert entry is not None  # the status is ok
                edges.append(Edge(name, "stage", entry.value, entry.validity, registered_by))
        return CoordinateGraph(edges)

    def _stage_variable(self, axis: str) -> Variable | None:
        return next((v for v in self.variables.values() if v.axis == axis), None)

    def _motor_matrix(self) -> Matrix:
        """Stage micrometres to motor steps: the actuators' own calibration."""
        factors = {}
        for axis in ("x", "y", "z"):
            variable = self._stage_variable(axis)
            steps = variable.steps_per_um if variable and variable.steps_per_um else 1.0
            factors[axis] = -steps if variable and variable.inverted else steps
        return scaling(**factors)

    # --- planning

    def plan(self, request: Request) -> Plan:
        """What `request` takes, judged by the state the image will be taken under."""
        channel = self.channels[request.channel]
        path = self.paths[channel.path]
        targets = {**channel.settings, **request.settings}
        state = {**self.values, **targets}
        plan = Plan(request=request, path=path.name)

        self._judge_needs(plan, path, state)
        at = request.at
        graph = self.graph(path, state)
        try:
            z_given = at.z if at.z is not None else 0.0
            point = graph.transform((at.x, at.y, z_given), at.system, "stage")
            plan.route = [at.system] + [
                edge.target if forwards else edge.source
                for edge, forwards in graph.route(at.system, "stage")
            ]
        except NoRoute:
            registered_by = self.systems.get(at.system, {}).get("registered_by")
            why = (
                f"{registered_by} is {self.status(registered_by, path, state).code}"
                if registered_by
                else f"nothing connects {at.system} to the stage"
            )
            plan.blocked.append(f"no way from {at.system} to the stage: {why}")
            return plan

        plan.target = {"x": float(point[0]), "y": float(point[1])}
        self._set_order(plan, targets)
        for axis in ("x", "y"):
            step = self._stage_setpoint(axis, plan.target[axis], graph)
            if step is not None:
                plan.moves.append(step)

        if at.z is not None:
            plan.target["z"] = float(point[2]) + at.z_offset
        else:
            self._plan_focus(plan, path, state, graph)
        if "z" in plan.target:
            plan.z = self._stage_setpoint("z", plan.target["z"], graph)
        return plan

    def _judge_needs(self, plan: Plan, path: LightPath, state: Mapping[str, Any]) -> None:
        quantities = self.quantities(path)
        system = self.systems.get(plan.request.at.system, {})
        if system.get("registered_by"):
            quantities = sorted({*quantities, system["registered_by"]})
        for quantity in quantities:
            status = self.status(quantity, path, state)
            calibration = self.calibrations[quantity]
            if status.ok:
                action = "ok"
            elif status.code == "missing" and calibration.nominal:
                action = "nominal"
            else:
                action = calibration.on_stale
            plan.needs.append(Need(quantity, self.key(quantity, path, state), status, action))
            if action == "block":
                plan.blocked.append(f"{quantity} is {status.code}: {status.reason}")
            elif action == "repair":
                self._add_repair(plan, quantity, path, state)

    def _add_repair(
        self, plan: Plan, quantity: str, path: LightPath, state: Mapping[str, Any]
    ) -> None:
        """Repair what `quantity` depends on first, as the deepest failure comes first."""
        for dependency in self.calibrations[quantity].depends_on:
            below = self.status(dependency, path, state)
            nominal = below.code == "missing" and self.calibrations[dependency].nominal
            if not below.ok and not nominal:
                self._add_repair(plan, dependency, path, state)
        if quantity not in plan.repairs:
            plan.repairs.append(quantity)

    def _set_order(self, plan: Plan, targets: Mapping[str, Any]) -> None:
        """Order what the channel sets: what the rules require first, and restored last."""
        guarded = {name for rule in self.rules for name in rule["require"]}
        current = dict(self.values)
        for rule in self.rules:
            moving = rule["moving"]
            if moving in targets and targets[moving] != self.values[moving]:
                for name, required in rule["require"].items():
                    if current[name] != required:
                        plan.before.append(self._setpoint(name, current[name], required))
                        current[name] = required
        for name, target in targets.items():
            if current[name] == target:
                continue
            step = self._setpoint(name, current[name], target)
            (plan.after if name in guarded else plan.moves).append(step)

    def _setpoint(self, name: str, current: Any, target: Any) -> Setpoint:  # noqa: ANN401
        variable = self.variables[name]
        return Setpoint(name, current, target, variable.actuator, target)

    def _stage_setpoint(self, axis: str, target: float, graph: CoordinateGraph) -> Setpoint | None:
        variable = self._stage_variable(axis)
        if variable is None or self.values[variable.name] == target:
            return None
        point = dict(zip(("x", "y", "z"), (0.0, 0.0, 0.0)))
        point[axis] = target
        steps = graph.transform((point["x"], point["y"], point["z"]), "stage", "motors")
        native = float(steps[("x", "y", "z").index(axis)])
        return Setpoint(
            variable.name, self.values[variable.name], target, variable.actuator, native
        )

    def _plan_focus(
        self, plan: Plan, path: LightPath, state: Mapping[str, Any], graph: CoordinateGraph
    ) -> None:
        """Z comes from the focus plane, computed forwards from x and y: never walked back."""
        if "focus_plane" not in self.calibrations:
            return
        if "focus_plane" in plan.repairs:
            plan.z_after_repairs = True
            return
        entry = self.entry("focus_plane", path, state)
        if entry is not None:
            plan.target["z"] = self._focus_z(entry, plan) + plan.request.at.z_offset

    @staticmethod
    def _focus_z(entry: Entry, plan: Plan) -> float:
        plane = entry.value
        return float(
            plane["z0"] + plane["tilt_x"] * plan.target["x"] + plane["tilt_y"] * plan.target["y"]
        )

    # --- applying

    def apply(self, plan: Plan) -> Record:
        """Do what `plan` says and take the image.

        Raises:
            Blocked: The plan cannot start; nothing has moved.
        """
        if plan.blocked:
            raise Blocked("; ".join(plan.blocked))
        for step in (*plan.before, *plan.moves):
            self._execute(step)
        path = self.paths[plan.path]
        for quantity in plan.repairs:
            self.calibrate(quantity, plan.path)
        z_step = plan.z
        if plan.z_after_repairs:
            entry = self.entry("focus_plane", path, self.values)
            assert entry is not None  # it was just repaired
            target = self._focus_z(entry, plan) + plan.request.at.z_offset
            plan.target["z"] = target
            z_step = self._stage_setpoint("z", target, self.graph(path, self.values))
        if z_step is not None:
            self._execute(z_step)
        for step in plan.after:
            self._execute(step)
        return self._acquire(plan, path)

    def _execute(self, step: Setpoint) -> None:
        self.values[step.variable] = step.target
        if step.actuator:
            self.motors[step.actuator] = step.native
        self.log.append(f"set {step.variable}")

    def pixel_scale(self, path: LightPath, state: Mapping[str, Any]) -> tuple[Matrix, Validity]:
        """Pixels to micrometres: measured if it can be relied on, else the nominal value."""
        entry = self.entry("pixel_to_sample", path, state)
        if entry is not None and self.status("pixel_to_sample", path, state).ok:
            return entry.value, entry.validity
        pixel_um = next(
            cube.properties["pixel_um"]
            for cube in self.cubes.values()
            if "pixel_um" in cube.properties and cube.name in path.cubes
        )
        magnification = 1.0
        for name in path.cubes:
            for variable in self.cubes[name].variables.values():
                properties = variable.values.get(state[variable.name], {})
                magnification *= properties.get("magnification", 1.0)
        binning = next(
            state[variable.name]
            for variable in self.variables.values()
            if variable.name.endswith(".binning")
        )
        size = pixel_um * binning / magnification
        return scaling(size, size), Validity.INFERRED

    def _acquire(self, plan: Plan, path: LightPath) -> Record:
        """Take the image, and write down what was true.

        The stage position is an offset the pixel scale does not touch: a pixel is at
        ``stage + scale @ (pixel - centre)``, so the stage position is the middle of the image.
        """
        state = dict(self.values)
        camera = next(
            self.cubes[name] for name in path.cubes if "width" in self.cubes[name].properties
        )
        binning = state[f"{camera.name}.binning"]
        width, height = (
            camera.properties["width"] // binning,
            camera.properties["height"] // binning,
        )
        scale, validity = self.pixel_scale(path, state)
        stage = {
            axis: float(state[variable.name])
            for axis in ("x", "y", "z")
            if (variable := self._stage_variable(axis)) is not None
        }
        matrix = (
            translation(stage.get("x", 0.0), stage.get("y", 0.0), stage.get("z", 0.0))
            @ scale
            @ translation(-(width - 1) / 2, -(height - 1) / 2)
        )
        shift = self.entry("chromatic_shift", path, state)
        if shift is not None and self.status("chromatic_shift", path, state).ok:
            matrix = translation(*shift.value) @ matrix
            validity = min(validity, shift.validity)

        image = f"image:{len(self.images) + 1}"
        key = self.key("pixel_to_sample", path, state)
        edge_name = f"pixel_to_sample:{key}"
        self.images.append(Edge(image, "stage", matrix, validity, edge_name))
        self.log.append(f"acquire {image}")
        needs = {
            quantity: Need(
                quantity,
                self.key(quantity, path, state),
                self.status(quantity, path, state),
                next(
                    (need.action for need in plan.needs if need.quantity == quantity),
                    "ok",
                ),
            )
            for quantity in self.quantities(path)
        }
        return Record(
            image=image,
            channel=plan.request.channel,
            path=path.name,
            matrix=matrix,
            validity=validity,
            edge_name=edge_name,
            stage=stage,
            values=state,
            calibrations=needs,
            acquired_at=self.clock(),
            frame=self.camera(self, height, width),
        )


def _cube(name: str, spec: Mapping[str, Any]) -> Cube:
    variables = {
        short: Variable(
            name=f"{name}.{short}",
            initial=declared.get("initial"),
            actuator=declared.get("actuator"),
            axis=declared.get("axis"),
            steps_per_um=declared.get("steps_per_um"),
            inverted=bool(declared.get("inverted", False)),
            unit=declared.get("unit"),
            values=declared.get("values") or {},
        )
        for short, declared in (spec.get("variables") or {}).items()
    }
    impacts = {
        quantity: Impact(
            selects=tuple((declared or {}).get("selects") or ()),
            uses=tuple((declared or {}).get("uses") or ()),
        )
        for quantity, declared in (spec.get("impacts") or {}).items()
    }
    properties = {
        key: value for key, value in spec.items() if key not in ("kind", "variables", "impacts")
    }
    return Cube(name, spec["kind"], variables, impacts, properties)
