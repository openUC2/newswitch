"""The microscope as the designer describes it: cubes, their elements, and how light connects them.

An instrument is a folder: its description (``microscope.yml``), the optics files it names, and
what the compiler found (`newswitch.instrument.compiler`). A server can run from it directly
(``NEWSWITCH_CONFIG=instruments/<name>/microscope.yml``).
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pint
import yaml

#: The description's name in an instrument's folder.
DESCRIPTION = "microscope.yml"
#: What a description states it is, followed by its version.
SPEC = "newswitch/instrument/"

_UNITS = pint.UnitRegistry()

#: The unit every quantity of an element is kept in.
_CANONICAL = {
    "wavelength": "nm",
    "width": "nm",
    "cut": "nm",
    "center": "nm",
    "excitation": "nm",
    "excitation_width": "nm",
    "emission": "nm",
    "emission_width": "nm",
    "f": "mm",
    "working_distance": "mm",
    "max_power": "mW",
    "clear_radius": "mm",
    "pitch": "um",
    "distance": "mm",
}


class SpecError(ValueError):
    """The description contradicts itself."""


def _canonical(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _UNITS.Quantity(value).to(_CANONICAL[key]).magnitude
        if key in _CANONICAL and isinstance(value, str)
        else value
        for key, value in values.items()
    }


@dataclass(frozen=True)
class Element:
    """An optical element: what it is, and the numbers that say what it does to light."""

    kind: str
    properties: Mapping[str, Any]


@dataclass(frozen=True)
class Variable:
    """A value of the instrument, and what changing it does to its cube's element."""

    name: str  # "objective.slot"
    cube: str
    verb: str  # moves | swaps | tunes
    initial: Any
    step: float | None = None
    along: str | None = None  # moves: x, y, or the optical axis
    actuator: str | None = None
    units: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    speed: float | None = None
    slots: Mapping[int, Element] | None = None


@dataclass(frozen=True)
class Cube:
    """Housing around an optical element, and what its actuators do to it."""

    name: str
    element: Element | None
    variables: Mapping[str, Variable]

    def element_at(self, state: Mapping[str, Any]) -> Element:
        """The element in place under `state`: a swap decides which one that is."""
        for variable in self.variables.values():
            if variable.verb == "swaps":
                assert variable.slots is not None
                return variable.slots[state[variable.name]]
        assert self.element is not None
        return self.element


@dataclass(frozen=True)
class Edge:
    """Light going from one cube to the next."""

    source: str
    target: str
    via: str | None = None
    side: str | None = None
    distance: float | str | None = None  # millimetres, or "focus"


@dataclass(frozen=True)
class Instrument:
    """A whole description."""

    name: str
    folder: Path
    sample: Mapping[str, Any]
    cubes: Mapping[str, Cube]
    illumination: tuple[Edge, ...]
    detection: tuple[Edge, ...]
    views: tuple[str, ...] = ()
    digest: str = ""
    #: What an old configuration ships besides its devices; an instrument has none of its own yet.
    assets: Mapping[str, str] = field(default_factory=dict)

    @property
    def variables(self) -> dict[str, Variable]:
        """Every variable, by its full name."""
        return {
            variable.name: variable
            for cube in self.cubes.values()
            for variable in cube.variables.values()
        }

    def initial_state(self) -> dict[str, Any]:
        """Every variable at its initial value."""
        return {name: variable.initial for name, variable in self.variables.items()}

    def swap_states(self) -> Iterator[dict[str, Any]]:
        """Every combination of what the swaps can put in place, the rest at its initial value."""
        swaps = [variable for variable in self.variables.values() if variable.verb == "swaps"]
        for values in itertools.product(*(list(v.slots or {}) for v in swaps)):
            yield {**self.initial_state(), **{v.name: value for v, value in zip(swaps, values)}}

    def detectors(self) -> list[str]:
        """The cubes that end a route: whatever holds a sensor."""
        return [
            cube.name
            for cube in self.cubes.values()
            if cube.element is not None and cube.element.kind == "sensor"
        ]

    def sources(self) -> list[str]:
        """The cubes light starts from."""
        return [
            cube.name
            for cube in self.cubes.values()
            if cube.element is not None and cube.element.kind == "source"
        ]

    def sample_cube(self) -> str:
        """The cube holding the sample."""
        return next(
            cube.name
            for cube in self.cubes.values()
            if cube.element is not None and cube.element.kind == "sample"
        )

    def routes(self, edges: tuple[Edge, ...], start: str, end: str) -> list[tuple[Edge, ...]]:
        """Every way light can go from `start` to `end` along `edges`."""
        found: list[tuple[Edge, ...]] = []

        def walk(at: str, walked: tuple[Edge, ...]) -> None:
            if at == end:
                found.append(walked)
                return
            for edge in edges:
                if edge.source == at and edge not in walked:
                    walk(edge.target, (*walked, edge))

        walk(start, ())
        return found


def _element(spec: Mapping[str, Any]) -> Element:
    properties = _canonical({key: value for key, value in spec.items() if key != "kind"})
    if "axes" in properties:
        properties["axes"] = {axis: _canonical(a) for axis, a in properties["axes"].items()}
    return Element(spec["kind"], properties)


def _variables(name: str, spec: Mapping[str, Any]) -> dict[str, Variable]:
    variables: dict[str, Variable] = {}
    for verb in ("moves", "tunes"):
        for short, declared in (spec.get(verb) or {}).items():
            variables[short] = Variable(
                name=f"{name}.{short}",
                cube=name,
                verb=verb,
                initial=declared["initial"],
                step=declared.get("step"),
                along=declared.get("along"),
                actuator=declared.get("actuator"),
                units=declared.get("units"),
                minimum=declared.get("min"),
                maximum=declared.get("max"),
                speed=declared.get("speed"),
            )
    for short, declared in (spec.get("swaps") or {}).items():
        variables[short] = Variable(
            name=f"{name}.{short}",
            cube=name,
            verb="swaps",
            initial=declared["initial"],
            actuator=declared.get("actuator"),
            slots={slot: _element(e) for slot, e in declared["slots"].items()},
        )
    return variables


def _edges(declared: list[Mapping[str, Any]]) -> tuple[Edge, ...]:
    edges = []
    for edge in declared:
        distance = edge.get("distance")
        if isinstance(distance, str) and distance != "focus":
            distance = _UNITS.Quantity(distance).to("mm").magnitude
        edges.append(Edge(edge["from"], edge["to"], edge.get("via"), edge.get("side"), distance))
    return tuple(edges)


def _digest(data: Mapping[str, Any]) -> str:
    """What a description says, so that rewording a comment does not outdate its tables."""
    encoded = json.dumps(data, sort_keys=True, default=str).encode()
    return hashlib.blake2b(encoded, digest_size=8).hexdigest()


def is_description(path: str | Path) -> bool:
    """Whether `path` is an instrument: a description, or a folder holding one."""
    path = Path(path)
    if path.is_dir():
        path = path / DESCRIPTION
    if not path.is_file() or path.suffix.lower() not in (".yml", ".yaml"):
        return False
    data = yaml.safe_load(path.read_text())
    return isinstance(data, dict) and str(data.get("spec", "")).startswith(SPEC)


def load(path: str | Path) -> Instrument:
    """The instrument described at `path`: a description, or a folder holding one.

    Raises:
        SpecError: It is not one, an edge names a cube that does not exist, or a detector has
            no route.
    """
    path = Path(path)
    if path.is_dir():
        path = path / DESCRIPTION
    data = yaml.safe_load(path.read_text())
    if not str(data.get("spec", "")).startswith(SPEC):
        raise SpecError(f"{path} does not say it is an instrument description")
    cubes = {
        name: Cube(
            name=name,
            element=_element(spec["element"]) if spec.get("element") else None,
            variables=_variables(name, spec),
        )
        for name, spec in data["cubes"].items()
    }
    instrument = Instrument(
        name=data["name"],
        folder=path.parent.resolve(),
        sample=_canonical(
            {**data["sample"], **_canonical(data["sample"].get("fluorophore") or {})}
        ),
        cubes=cubes,
        illumination=_edges(data["illumination"]),
        detection=_edges(data["detection"]),
        views=tuple((data.get("ui") or {}).get("views") or ()),
        digest=_digest(data),
    )
    problems = [
        f"an edge names no cube {name!r}"
        for edge in (*instrument.illumination, *instrument.detection)
        for name in (edge.source, edge.target)
        if name not in cubes
    ]
    problems += [
        f"no light reaches {detector}"
        for detector in instrument.detectors()
        if not instrument.routes(instrument.detection, instrument.sample_cube(), detector)
    ]
    if problems:
        raise SpecError("; ".join(problems))
    return instrument
