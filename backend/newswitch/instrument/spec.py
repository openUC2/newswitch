"""The microscope as the designer describes it: cubes, their elements, and how light connects them.

An instrument is a folder: its description (``microscope.yml``), the optics files it names, and
what the compiler found (`newswitch.instrument.compiler`). A server can run from it directly
(``NEWSWITCH_CONFIG=instruments/<name>/microscope.yml``).

`Instrument` is that file, validated, all the way down in pydantic dataclasses: unknown keys, a
value of the wrong type or unit, a missing one, or parts that contradict each other are errors,
all reported at once with their path in the file.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import field
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import pint
import yaml
from pydantic import (
    BeforeValidator,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic.dataclasses import dataclass

from newswitch.instrument.errors import SpecError, problems_of
from newswitch.instrument.hardware import STRICT, Hardware
from newswitch.instrument.ui import UiConfig
from newswitch.settings import Settings

#: The description's name in an instrument's folder.
DESCRIPTION = "microscope.yml"
#: What a description states it is, followed by its version.
SPEC = "newswitch/instrument/"

_UNITS = pint.UnitRegistry()


def _in_unit(unit: str) -> Callable[[Any], Any]:
    """Validator of a quantity: ``"488 nm"`` becomes a number in `unit`; a bare number already is."""

    def convert(value: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        if not isinstance(value, str):
            return value
        try:
            return float(_UNITS.Quantity(value).to(unit).magnitude)
        except (pint.errors.PintError, TypeError, ValueError, AttributeError, SyntaxError) as exc:
            raise ValueError(f"{value!r} is not a quantity in {unit}") from exc

    return convert


#: The unit every quantity is kept in.
Nanometres = Annotated[StrictFloat, BeforeValidator(_in_unit("nm"))]
Millimetres = Annotated[StrictFloat, BeforeValidator(_in_unit("mm"))]
Micrometres = Annotated[StrictFloat, BeforeValidator(_in_unit("um"))]
Milliwatts = Annotated[StrictFloat, BeforeValidator(_in_unit("mW"))]
Hertz = Annotated[StrictFloat, Field(gt=0.0), BeforeValidator(_in_unit("Hz"))]
#: A fraction of the light: of what arrives, or of a filter's band.
Fraction = Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
#: A value of the instrument: whole numbers (a binning) stay whole.
Number = StrictInt | StrictFloat


@dataclass(frozen=True, config=STRICT)
class Source:
    """Where light starts."""

    kind: Literal["source"]
    wavelength: Nanometres
    width: Nanometres
    max_power: Milliwatts
    coherent: StrictBool = False


@dataclass(frozen=True, config=STRICT)
class Lens:
    """A lens: from its prescription, or ideal, with only its focal length known."""

    kind: Literal["lens"]
    name: str | None = None
    f: Millimetres | None = None
    na: Annotated[StrictFloat, Field(gt=0.0)] | None = None
    working_distance: Millimetres | None = None
    prescription: str | None = None
    clear_radius: Millimetres | None = None

    @model_validator(mode="after")
    def _has_optics(self) -> Self:
        if self.f is None and self.prescription is None:
            raise ValueError("a lens needs a focal length (f) or a prescription")
        return self


@dataclass(frozen=True, config=STRICT)
class SampleHolder:
    """Where the sample is."""

    kind: Literal["sample"]


@dataclass(frozen=True, config=STRICT)
class SensorAxis:
    """One direction of a sensor."""

    size: Annotated[StrictInt, Field(gt=0)]
    pitch: Micrometres


@dataclass(frozen=True, config=STRICT)
class Sensor:
    """What light ends on: its size lives on its axes, and nowhere else."""

    kind: Literal["sensor"]
    axes: dict[Literal["x", "y"], SensorAxis]

    @model_validator(mode="after")
    def _both_axes(self) -> Self:
        if set(self.axes) != {"x", "y"}:
            raise ValueError("a sensor needs the axes x and y")
        return self


@dataclass(frozen=True, config=STRICT)
class Filter:
    """A band of light let through; with no band, an open position."""

    kind: Literal["filter"]
    name: str | None = None
    center: Nanometres | None = None
    width: Nanometres | None = None
    transmission: Fraction = 1.0

    @model_validator(mode="after")
    def _whole_band(self) -> Self:
        if (self.center is None) != (self.width is None):
            raise ValueError("a filter's band needs both its center and its width")
        return self


@dataclass(frozen=True, config=STRICT)
class Dichroic:
    """Reflects what is below its cut, lets through what is above."""

    kind: Literal["dichroic"]
    cut: Nanometres


@dataclass(frozen=True, config=STRICT)
class Splitter:
    """Sends light two ways."""

    kind: Literal["splitter"]
    reflect: Fraction
    transmit: Fraction


#: An optical element: what it is, and the numbers that say what it does to light.
Element = Annotated[
    Source | Lens | SampleHolder | Sensor | Filter | Dichroic | Splitter,
    Field(discriminator="kind"),
]


@dataclass(frozen=True, config=STRICT, kw_only=True)
class Move:
    """A value of the instrument: an actuator moves its cube's element."""

    name: str  # "stage.x"; its cube says it
    cube: str
    verb: Literal["moves"] = "moves"
    along: Literal["x", "y", "axis"]  # the optical axis, or across it
    initial: Number
    actuator: str | None = None
    step: Number | None = None
    min: StrictFloat | None = None
    max: StrictFloat | None = None
    speed: Annotated[StrictFloat, Field(gt=0.0)] | None = None
    units: str | None = None

    @model_validator(mode="after")
    def _starts_in_range(self) -> Self:
        if self.min is not None and self.initial < self.min:
            raise ValueError(f"initial {self.initial} is below min {self.min}")
        if self.max is not None and self.initial > self.max:
            raise ValueError(f"initial {self.initial} is above max {self.max}")
        return self


@dataclass(frozen=True, config=STRICT, kw_only=True)
class Tune:
    """A value of the instrument: an actuator tunes its cube's element."""

    name: str  # "laser-488.power"; its cube says it
    cube: str
    verb: Literal["tunes"] = "tunes"
    initial: Number
    actuator: str | None = None
    step: Number | None = None
    units: str | None = None


@dataclass(frozen=True, config=STRICT, kw_only=True)
class Swap:
    """A value of the instrument: an actuator swaps which element is in place in its cube."""

    name: str  # "objective.slot"; its cube says it
    cube: str
    verb: Literal["swaps"] = "swaps"
    initial: StrictInt
    slots: dict[StrictInt, Element]
    actuator: str | None = None

    @model_validator(mode="after")
    def _starts_in_a_slot(self) -> Self:
        if self.initial not in self.slots:
            raise ValueError(f"initial {self.initial} is none of the slots {sorted(self.slots)}")
        return self


#: A value of the instrument, and what changing it does to its cube's element.
Variable = Move | Tune | Swap

#: What each kind of element must be able to change, for the server to have a control for it.
_NEEDS_TUNES = {"source": {"power"}, "sensor": {"exposure", "gain", "binning"}}


@dataclass(frozen=True, config=STRICT, kw_only=True)
class Cube:
    """Housing around an optical element, and what its actuators do to it."""

    name: str  # its key in the description
    element: Element | None = None
    moves: dict[str, Move] = field(default_factory=dict)
    tunes: dict[str, Tune] = field(default_factory=dict)
    swaps: dict[str, Swap] = field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _name_variables(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        if not isinstance(data, Mapping):
            return data
        named = dict(data)
        for section in ("moves", "tunes", "swaps"):
            if isinstance(data.get(section), Mapping):
                named[section] = {
                    short: {
                        **entry,
                        "name": f"{data.get('name')}.{short}",
                        "cube": data.get("name"),
                    }
                    if isinstance(entry, Mapping)
                    else entry
                    for short, entry in data[section].items()
                }
        return named

    @model_validator(mode="after")
    def _has_one_element(self) -> Self:
        if (self.element is None) == (not self.swaps):
            raise ValueError("a cube has an element, or swaps between some: exactly one of them")
        if self.element is not None:
            missing = _NEEDS_TUNES.get(self.element.kind, set()) - set(self.tunes)
            if missing:
                raise ValueError(f"a {self.element.kind} must tune {sorted(missing)}")
        return self

    @property
    def variables(self) -> dict[str, Variable]:
        """What its actuators change, by short name."""
        return {**self.moves, **self.tunes, **self.swaps}

    def element_at(self, state: Mapping[str, Any]) -> Element:
        """The element in place under `state`: a swap decides which one that is."""
        for swap in self.swaps.values():
            return swap.slots[state[swap.name]]
        assert self.element is not None
        return self.element


@dataclass(frozen=True, config=STRICT)
class Edge:
    """Light going from one cube to the next."""

    source: str = Field(validation_alias="from")
    target: str = Field(validation_alias="to")
    via: Literal["reflect", "transmit"] | None = None
    side: Literal["epi", "transmitted"] | None = None
    distance: Millimetres | Literal["focus"] | None = None  # or the lens's own focal length


@dataclass(frozen=True, config=STRICT)
class Fluorophore:
    """What the sample emits, and what makes it."""

    excitation: Nanometres
    excitation_width: Nanometres
    emission: Nanometres
    emission_width: Nanometres
    quantum_yield: Fraction


@dataclass(frozen=True, config=STRICT)
class Sample:
    """What is on the stage."""

    fluorophore: Fluorophore
    transmit: Fraction  # light going straight through (transmitted light)
    reflect: Fraction  # light coming back the way it came (epi)


@dataclass(frozen=True, config=STRICT)
class Objective:
    """The swap that changes objectives."""

    swap: str  # "objective.slot"
    reference_tube: Millimetres  # what a lens's magnification is stated against


@dataclass(frozen=True, config=STRICT)
class Filters:
    """The swap that changes filters."""

    swap: str  # "filter-wheel.slot"


@dataclass(frozen=True, config=STRICT)
class SourcePart:
    """A light source the server controls."""

    cube: str
    full_intensity: Annotated[StrictFloat, Field(gt=0.0)]  # its intensity runs from 0 to this


@dataclass(frozen=True, config=STRICT)
class DetectorPart:
    """A detector the server controls."""

    cube: str
    frame_rate: Hertz  # how often it streams


@dataclass(frozen=True, config=STRICT)
class Parts:
    """What the server has a control for, in which role, and by which slot. Nothing is inferred."""

    stage: str | None = None  # the cube holding the sample, if something moves it
    objective: Objective | None = None
    filters: Filters | None = None
    sources: dict[StrictInt, SourcePart] = field(default_factory=dict)
    detectors: dict[StrictInt, DetectorPart] = field(default_factory=dict)


@dataclass(frozen=True, config=STRICT, kw_only=True)
class Instrument:
    """A whole ``microscope.yml``: only ever read. `load` adds where it is and what it says."""

    folder: Path
    digest: str
    spec: Annotated[str, Field(pattern=f"^{SPEC}")]
    name: str
    sample: Sample
    cubes: dict[str, Cube]
    illumination: tuple[Edge, ...]
    detection: tuple[Edge, ...]
    parts: Parts
    settings: Settings
    ui: UiConfig | None = None  # what the frontend shows
    agent_ui: UiConfig | None = None  # what Orkestrator shows
    hardware: Hardware = field(default_factory=Hardware)

    @model_validator(mode="before")
    @classmethod
    def _name_cubes(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        if not isinstance(data, Mapping) or not isinstance(data.get("cubes"), Mapping):
            return data
        return {
            **data,
            "cubes": {
                name: {**cube, "name": name} if isinstance(cube, Mapping) else cube
                for name, cube in data["cubes"].items()
            },
        }

    @model_validator(mode="after")
    def _agrees_with_itself(self) -> Self:
        if not any(
            cube.element is not None and cube.element.kind == "sample"
            for cube in self.cubes.values()
        ):
            raise ValueError("no cube holds the sample")
        problems = [
            f"an edge names no cube {name!r}"
            for edge in (*self.illumination, *self.detection)
            for name in (edge.source, edge.target)
            if name not in self.cubes
        ]
        problems += [
            f"no light reaches {detector}"
            for detector in self.detectors()
            if not self.routes(self.detection, self.sample_cube(), detector)
        ]
        problems += _parts_problems(self)
        problems += _hardware_problems(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self

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
        for values in itertools.product(*(list(v.slots) for v in swaps)):
            yield {**self.initial_state(), **{v.name: value for v, value in zip(swaps, values)}}

    def detectors(self) -> list[str]:
        """The cubes of the detectors, by slot."""
        return [part.cube for _, part in sorted(self.parts.detectors.items())]

    def sources(self) -> list[str]:
        """The cubes of the light sources, by slot."""
        return [part.cube for _, part in sorted(self.parts.sources.items())]

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


_INSTRUMENT = TypeAdapter(Instrument)

#: The sections of a description the compiler does not look at.
_NOT_OPTICS = ("hardware", "ui", "agent_ui", "parts", "settings")


def _digest(data: Mapping[str, Any]) -> str:
    """What a description says of its optics: nothing but a change to them outdates a table."""
    optics = {key: value for key, value in data.items() if key not in _NOT_OPTICS}
    encoded = json.dumps(optics, sort_keys=True, default=str).encode()
    return hashlib.blake2b(encoded, digest_size=8).hexdigest()


def _slot_problems(role: str, slots: Iterable[int]) -> list[str]:
    """Slots count from 1 without a gap: the managers keep their parts in a list."""
    slots = sorted(slots)
    return (
        []
        if slots == list(range(1, len(slots) + 1))
        else [f"parts.{role}: slots {slots} must count from 1"]
    )


def _listed_problems(instrument: Instrument, role: str, kind: str, listed: list[str]) -> list[str]:
    """Each cube of `kind` has one slot in `role`, and only those have."""
    holding = [
        cube.name
        for cube in instrument.cubes.values()
        if cube.element is not None and cube.element.kind == kind
    ]
    problems = [f"parts.{role}: {name!r} holds no {kind}" for name in listed if name not in holding]
    problems += [
        f"parts.{role}: the {kind} {name!r} has no slot" for name in holding if name not in listed
    ]
    problems += [
        f"parts.{role}: {name!r} has two slots" for name in set(listed) if listed.count(name) > 1
    ]
    return problems


def _swap_problems(instrument: Instrument, role: str, swap: str, kind: type) -> list[str]:
    """What is wrong with the swap that `role` says changes elements of `kind`."""
    variable = instrument.variables.get(swap)
    if variable is None or variable.verb != "swaps":
        return [f"parts.{role}: there is no swap {swap!r}"]
    return [
        f"parts.{role}: slot {slot} of {swap} is no {kind.__name__.lower()}"
        for slot, element in variable.slots.items()
        if not isinstance(element, kind)
    ]


def _parts_problems(instrument: Instrument) -> list[str]:
    """What the ``parts`` section says that the description does not have."""
    parts = instrument.parts
    problems = _slot_problems("sources", parts.sources) + _slot_problems(
        "detectors", parts.detectors
    )
    problems += _listed_problems(instrument, "sources", "source", instrument.sources())
    problems += _listed_problems(instrument, "detectors", "sensor", instrument.detectors())
    if parts.stage is not None:
        cube = instrument.cubes.get(parts.stage)
        if cube is None or cube.element is None or cube.element.kind != "sample":
            problems.append(f"parts.stage: {parts.stage!r} holds no sample")
        elif not cube.moves:
            problems.append(f"parts.stage: nothing moves {parts.stage!r}")
        else:
            problems += [
                f"parts.stage: a stage moves along x, y, z and a, not {short!r}"
                for short in cube.moves
                if short not in ("x", "y", "z", "a")
            ]
    if parts.objective is not None:
        swap = parts.objective.swap
        problems += _swap_problems(instrument, "objective", swap, Lens)
        variable = instrument.variables.get(swap)
        if variable is not None and variable.verb == "swaps":
            problems += [
                f"{swap}: an objective needs its f and na, slot {slot} has not"
                for slot, element in variable.slots.items()
                if isinstance(element, Lens) and (element.f is None or element.na is None)
            ]
    if parts.filters is not None:
        problems += _swap_problems(instrument, "filters", parts.filters.swap, Filter)
    return problems


def _hardware_problems(instrument: Instrument) -> list[str]:
    """What its ``hardware`` section names that the description does not have."""
    named = {variable.actuator for variable in instrument.variables.values()}
    problems = [
        f"hardware: no variable has the actuator {name!r}"
        for name in instrument.hardware.actuators
        if name not in named
    ]
    problems += [
        f"hardware: there is no sensor {name!r} for a camera"
        for name in instrument.hardware.cameras
        if name not in instrument.detectors()
    ]
    # A stage manager moves x along the board's X: another axis would silently not move.
    stage = instrument.parts.stage
    moves = instrument.cubes[stage].moves if stage in instrument.cubes else {}
    for short, variable in moves.items():
        actuator = instrument.hardware.actuators.get(variable.actuator or "")
        if actuator is not None and actuator.axis != short.upper():
            problems.append(
                f"hardware: {variable.name} must be on axis {short.upper()}, not {actuator.axis!r}"
            )
    return problems


def load(path: str | Path) -> Instrument:
    """The instrument described at `path`: a description, or a folder holding one.

    Raises:
        SpecError: It is not one, or it does not validate. Every problem is listed.
    """
    path = Path(path)
    if path.is_dir():
        path = path / DESCRIPTION
    if not path.is_file():
        raise SpecError(f"{path} does not exist")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or not str(data.get("spec", "")).startswith(SPEC):
        raise SpecError(f"{path} does not say it is an instrument description")
    try:
        return _INSTRUMENT.validate_python(
            {**data, "folder": path.parent.resolve(), "digest": _digest(data)}
        )
    except ValidationError as exc:
        raise SpecError(f"{path}: " + "; ".join(problems_of(exc))) from exc
