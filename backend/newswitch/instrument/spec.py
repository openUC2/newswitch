"""The microscope as the designer describes it: cubes, their elements, and how light connects them.

An instrument is a folder: its description (``microscope.yml``) and the optics files it names. A
server computes what it does when it starts (`newswitch.instrument.compiler`), and runs from it directly
(``NEWSWITCH_CONFIG=instruments/<name>/microscope.yml``).

`Instrument` is that file, validated, all the way down in pydantic dataclasses: unknown keys, a
value of the wrong type or unit, a missing one, or parts that contradict each other are errors,
all reported at once with their path in the file.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import field
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import pint
import yaml
from pydantic import (
    BeforeValidator,
    Field,
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
#: The library of components a description can name, and what an entry states it is.
COMPONENTS = Path(__file__).parent / "components"
COMPONENT_SPEC = "newswitch/component/"

_UNITS = pint.UnitRegistry()


def _in_unit(unit: str) -> Callable[[Any], Any]:
    """Validator of a quantity: ``"488 nm"`` becomes a number in `unit`; a bare number is refused."""

    def convert(value: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        if not isinstance(value, str):
            raise ValueError(f"{value!r} needs its unit: a quantity in {unit}, such as '1 {unit}'")
        try:
            return float(_UNITS.Quantity(value).to(unit).magnitude)
        except (pint.errors.PintError, TypeError, ValueError, AttributeError, SyntaxError) as exc:
            raise ValueError(f"{value!r} is not a quantity in {unit}") from exc

    return convert


#: The unit every quantity is kept in.
Nanometres = Annotated[StrictFloat, BeforeValidator(_in_unit("nm"))]
Millimetres = Annotated[StrictFloat, BeforeValidator(_in_unit("mm"))]
Micrometres = Annotated[StrictFloat, BeforeValidator(_in_unit("um"))]
Degrees = Annotated[StrictFloat, BeforeValidator(_in_unit("deg"))]
Picoseconds = Annotated[StrictFloat, BeforeValidator(_in_unit("ps"))]
Nanoseconds = Annotated[StrictFloat, BeforeValidator(_in_unit("ns"))]
Milliwatts = Annotated[StrictFloat, BeforeValidator(_in_unit("mW"))]
Hertz = Annotated[StrictFloat, Field(gt=0.0), BeforeValidator(_in_unit("Hz"))]
#: How fast something moves.
MicrometresPerSecond = Annotated[StrictFloat, Field(gt=0.0), BeforeValidator(_in_unit("um/s"))]
#: A fraction of the light: of what arrives, or of a filter's band.
Fraction = Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
#: A value of the instrument: whole numbers (a binning) stay whole.
Number = StrictInt | StrictFloat


def _from_library(folder: str) -> Callable[[Any], Any]:
    """Validator of a part that can be named: what the library entry of that name states."""

    def read(value: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        if not isinstance(value, str):
            return value
        library = Path(__file__).parent / folder
        path = library / f"{value}.yml"
        if not path.is_file():
            known = sorted(entry.stem for entry in library.glob("*.yml"))
            raise ValueError(f"there is no {value!r} in {folder}: there are {known}")
        return yaml.safe_load(path.read_text())

    return read


@dataclass(frozen=True, config=STRICT)
class Line:
    """A band of light a source emits."""

    center: Nanometres
    width: Nanometres


def _as_lines(value: Any) -> Any:  # noqa: ANN401 - raw input of any shape
    return [value] if isinstance(value, Mapping) else value


@dataclass(frozen=True, config=STRICT)
class Source:
    """Where light starts: what it emits, as one line or several."""

    kind: Literal["source"]
    emits: Literal["laser", "led", "lamp"]
    spectrum: Annotated[tuple[Line, ...], Field(min_length=1), BeforeValidator(_as_lines)]
    max_power: Milliwatts
    repetition: Hertz | None = None  # a pulsed source's rate

    @property
    def wavelength(self) -> float:
        """Where most of its light is, for what shows one number."""
        return self.spectrum[0].center


#: Refractive indices of what an objective can look through, by name.
_IMMERSIONS = {"air": 1.0, "water": 1.33, "glycerol": 1.47, "oil": 1.515}


def _as_index(value: Any) -> Any:  # noqa: ANN401 - raw input of any shape
    if isinstance(value, str):
        if value not in _IMMERSIONS:
            raise ValueError(f"{value!r} is none of {sorted(_IMMERSIONS)}, or an index")
        return _IMMERSIONS[value]
    return value


@dataclass(frozen=True, config=STRICT)
class Lens:
    """A lens: from its prescription, or ideal, with only its focal length known.

    One that states an NA looks at the sample through something: `immersion` says what.
    """

    kind: Literal["lens"]
    name: str | None = None
    f: Millimetres | None = None
    na: Annotated[StrictFloat, Field(gt=0.0)] | None = None
    immersion: Annotated[StrictFloat, Field(ge=1.0), BeforeValidator(_as_index)] | None = None
    magnification: Annotated[StrictFloat, Field(gt=0.0)] | None = None  # as its maker states it
    working_distance: Millimetres | None = None
    prescription: str | None = None
    clear_radius: Millimetres | None = None

    @model_validator(mode="after")
    def _has_optics(self) -> Self:
        if self.f is None and self.prescription is None:
            raise ValueError("a lens needs a focal length (f) or a prescription")
        if self.prescription is not None and self.clear_radius is None:
            raise ValueError("a lens from a prescription needs its clear_radius")
        if self.na is not None:
            if self.immersion is None:
                raise ValueError("a lens with an NA needs its immersion: air, water, oil, ...")
            if self.na >= self.immersion:
                raise ValueError(f"an NA of {self.na} needs more than an index of {self.immersion}")
        return self

    @property
    def index(self) -> float:
        """The refractive index on its object's side."""
        return self.immersion if self.immersion is not None else 1.0


@dataclass(frozen=True, config=STRICT)
class BandPass:
    """Lets one band through."""

    type: Literal["bandpass"]
    center: Nanometres
    width: Nanometres
    peak: Fraction
    edge: Nanometres  # how sharply it falls off
    od: Annotated[StrictFloat, Field(gt=0.0)] | None = None  # how much it blocks at best


@dataclass(frozen=True, config=STRICT)
class LongPass:
    """Lets through what is above its cut."""

    type: Literal["longpass"]
    cut: Nanometres
    peak: Fraction
    edge: Nanometres
    od: Annotated[StrictFloat, Field(gt=0.0)] | None = None


@dataclass(frozen=True, config=STRICT)
class ShortPass:
    """Lets through what is below its cut."""

    type: Literal["shortpass"]
    cut: Nanometres
    peak: Fraction
    edge: Nanometres
    od: Annotated[StrictFloat, Field(gt=0.0)] | None = None


@dataclass(frozen=True, config=STRICT)
class Band:
    """One band of a filter with several."""

    center: Nanometres
    width: Nanometres


@dataclass(frozen=True, config=STRICT)
class MultiBand:
    """Lets several bands through, such as a quad-band dichroic."""

    type: Literal["multiband"]
    bands: Annotated[tuple[Band, ...], Field(min_length=1)]
    peak: Fraction
    edge: Nanometres
    od: Annotated[StrictFloat, Field(gt=0.0)] | None = None


@dataclass(frozen=True, config=STRICT)
class Neutral:
    """Lets the same share of everything through."""

    type: Literal["neutral"]
    transmission: Fraction


@dataclass(frozen=True, config=STRICT)
class Table:
    """A curve as measured: nanometres against transmission."""

    type: Literal["table"]
    points: Annotated[tuple[tuple[StrictFloat, StrictFloat], ...], Field(min_length=2)]


#: What a filter or dichroic lets through, at each wavelength.
Curve = Annotated[
    BandPass | LongPass | ShortPass | MultiBand | Neutral | Table,
    Field(discriminator="type"),
]
_Curve = Annotated[Curve, BeforeValidator(_from_library("curves"))]


@dataclass(frozen=True, config=STRICT)
class Fluorophore:
    """What a sample emits, and what makes it."""

    excitation: Nanometres
    excitation_width: Nanometres
    emission: Nanometres
    emission_width: Nanometres
    quantum_yield: Fraction
    lifetime: Nanoseconds | None = None  # what a detector timing its photons sees


@dataclass(frozen=True, config=STRICT)
class Pattern:
    """What a simulated sample looks like: random beads on a slide."""

    beads: Annotated[StrictInt, Field(ge=0)]
    radius: Micrometres
    extent: Millimetres = 6.0  # how wide all of the slide is
    resolution: Micrometres = 2.0  # how finely it is rendered
    darkens: Fraction = 0.6  # how much of what passes straight through a bead takes


@dataclass(frozen=True, config=STRICT)
class Simulation:
    """One thing that can be on the holder: without a fluorophore, it emits nothing.

    `absorbed` is the share of the light at its excitation peak that a bead on the path takes up.
    """

    transmit: Fraction  # light going straight through (transmitted light)
    reflect: Fraction  # light coming back the way it came (epi)
    pattern: Pattern
    fluorophore: Annotated[Fluorophore, BeforeValidator(_from_library("fluorophores"))] | None = (
        None
    )
    absorbed: Fraction | None = None

    @model_validator(mode="after")
    def _absorbs_what_it_emits(self) -> Self:
        if (self.fluorophore is None) != (self.absorbed is None):
            raise ValueError("a fluorophore and how much it absorbed come together")
        return self


@dataclass(frozen=True, config=STRICT)
class SampleHolder:
    """Where the sample is, and what can be on it, by name: `Settings.simulation` picks one."""

    kind: Literal["sample"]
    simulations: Annotated[dict[str, Simulation], Field(min_length=1)]


@dataclass(frozen=True, config=STRICT)
class Readout:
    """How light on a detector becomes numbers: quantum efficiency, noise and range."""

    qe: Fraction
    electrons_per_count: Annotated[StrictFloat, Field(gt=0.0)]
    read_noise: Annotated[StrictFloat, Field(ge=0.0)]  # in electrons
    offset: Annotated[StrictFloat, Field(ge=0.0)]  # in counts
    full_well: Annotated[StrictInt, Field(gt=0)]  # in electrons
    bit_depth: Annotated[StrictInt, Field(ge=1, le=32)]
    binning: Literal["average", "sum"] = "average"


_Readout = Annotated[Readout, BeforeValidator(_from_library("readouts"))]


@dataclass(frozen=True, config=STRICT)
class SensorAxis:
    """One direction of a sensor."""

    size: Annotated[StrictInt, Field(gt=0)]
    pitch: Micrometres


@dataclass(frozen=True, config=STRICT)
class ColorFilter:
    """The band one color of a sensor sees."""

    center: Nanometres
    width: Nanometres


@dataclass(frozen=True, config=STRICT)
class Sensor:
    """What light ends on: its size lives on its axes, and nowhere else.

    `colors` makes it a color camera: one image per color, each through its own band, by name.
    """

    kind: Literal["sensor"]
    axes: dict[Literal["x", "y"], SensorAxis]
    readout: _Readout
    colors: dict[str, ColorFilter] = field(default_factory=dict)
    rotation: Degrees | None = None  # how it is mounted, against the sample's axes
    flip: Literal["x", "y"] | None = None  # along which of its axes it is mirrored

    @model_validator(mode="after")
    def _both_axes(self) -> Self:
        if set(self.axes) != {"x", "y"}:
            raise ValueError("a sensor needs the axes x and y")
        return self


@dataclass(frozen=True, config=STRICT)
class Filter:
    """What light it lets through; with no curve, an open position."""

    kind: Literal["filter"]
    name: str | None = None
    curve: _Curve | None = None


@dataclass(frozen=True, config=STRICT)
class Dichroic:
    """Lets through what its curve says, and reflects the rest."""

    kind: Literal["dichroic"]
    curve: _Curve


@dataclass(frozen=True, config=STRICT)
class Splitter:
    """Sends light two ways."""

    kind: Literal["splitter"]
    reflect: Fraction
    transmit: Fraction


@dataclass(frozen=True, config=STRICT)
class ScanAxis:
    """One direction of a scan: how many steps, and the optical angle of one.

    Optical, not mechanical: a mirror turned by a degree turns the beam by two.
    """

    size: Annotated[StrictInt, Field(gt=0)]
    step: Degrees


@dataclass(frozen=True, config=STRICT)
class Scanner:
    """Turns the beam: a scanned image's size lives on its axes, as a sensor's does."""

    kind: Literal["scanner"]
    axes: dict[Literal["x", "y"], ScanAxis]

    @model_validator(mode="after")
    def _both_axes(self) -> Self:
        if set(self.axes) != {"x", "y"}:
            raise ValueError("a scanner needs the axes x and y")
        return self


@dataclass(frozen=True, config=STRICT)
class Pinhole:
    """An aperture in the detection path. Nothing rejects out-of-focus light yet: a sample is flat."""

    kind: Literal["pinhole"]
    diameter: Micrometres


@dataclass(frozen=True, config=STRICT)
class MicrotimeAxis:
    """How a detector bins when a photon arrives after its pulse."""

    size: Annotated[StrictInt, Field(gt=0)]
    step: Picoseconds


@dataclass(frozen=True, config=STRICT)
class PointDetector:
    """Light ends on one point: what is wired to it walks it through an image."""

    kind: Literal["point_detector"]
    readout: _Readout
    axes: dict[Literal["microtime"], MicrotimeAxis] = field(default_factory=dict)


#: An optical element: what it is, and the numbers that say what it does to light.
Element = Annotated[
    Source
    | Lens
    | SampleHolder
    | Sensor
    | Filter
    | Dichroic
    | Splitter
    | Scanner
    | Pinhole
    | PointDetector,
    Field(discriminator="kind"),
]


#: The unit each dimension of a variable is kept in; what is stated can be in any unit of it.
_VARIABLE_UNITS = (("[length]", "um"), ("[time]", "ms"), ("[power]", "mW"), ("[frequency]", "Hz"))


def _variable_quantity(text: str) -> tuple[float, str]:
    """A variable's value as stated, as a number in the unit kept for its dimension, and that unit."""
    stripped = text.strip()
    try:
        if stripped.endswith("dB"):  # a ratio: pint would take it for one, and lose the unit
            return float(stripped.removesuffix("dB")), "dB"
        quantity = _UNITS.Quantity(stripped)
        for dimension, unit in _VARIABLE_UNITS:
            if quantity.check(dimension):
                return float(quantity.to(unit).magnitude), unit
        if str(quantity.units) in ("degree", "radian"):
            return float(quantity.to("deg").magnitude), "deg"
    except (pint.errors.PintError, TypeError, ValueError, AttributeError, SyntaxError) as exc:
        raise ValueError(f"{text!r} is not a quantity") from exc
    raise ValueError(f"{text!r} is in no unit a variable can have")


def _in_one_unit(data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
    """A variable's numbers, all in one unit, which it then names: a bare number has none."""
    if not isinstance(data, Mapping):
        return data
    stated = {
        key: data[key] for key in ("initial", "step", "min", "max") if data.get(key) is not None
    }
    if not any(isinstance(value, str) for value in stated.values()):
        return data
    converted = {}
    units = set()
    for key, value in stated.items():
        if not isinstance(value, str):
            raise ValueError(f"{key}: {value!r} needs its unit, as the others have one")
        converted[key], unit = _variable_quantity(value)
        units.add(unit)
    if len(units) > 1:
        raise ValueError(f"its values are of different kinds: {sorted(units)}")
    return {**data, **converted, "unit": units.pop()}


def _starts_in_range(variable: Any) -> Any:  # noqa: ANN401 - a move or a tune
    """A variable whose initial value is within its limits, or an error."""
    if variable.min is not None and variable.initial < variable.min:
        raise ValueError(f"initial {variable.initial} is below min {variable.min}")
    if variable.max is not None and variable.initial > variable.max:
        raise ValueError(f"initial {variable.initial} is above max {variable.max}")
    return variable


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
    min: Number | None = None
    max: Number | None = None
    speed: MicrometresPerSecond | None = None
    unit: str = ""  # what its numbers are in, from how they are stated

    @model_validator(mode="before")
    @classmethod
    def _one_unit(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        return _in_one_unit(data)

    @model_validator(mode="after")
    def _starts_in_range(self) -> Self:
        return _starts_in_range(self)


@dataclass(frozen=True, config=STRICT, kw_only=True)
class Tune:
    """A value of the instrument: an actuator tunes its cube's element."""

    name: str  # "laser_488.power"; its cube says it
    cube: str
    verb: Literal["tunes"] = "tunes"
    initial: Number
    actuator: str | None = None
    step: Number | None = None
    min: Number | None = None
    max: Number | None = None
    unit: str = ""  # what its numbers are in, from how they are stated

    @model_validator(mode="before")
    @classmethod
    def _one_unit(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        return _in_one_unit(data)

    @model_validator(mode="after")
    def _starts_in_range(self) -> Self:
        return _starts_in_range(self)


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


@dataclass(frozen=True, config=STRICT)
class OutSignal:
    """What a part sends down a wire: the axes its events walk through, if any."""

    axes: tuple[Literal["y", "x"], ...] = ()


@dataclass(frozen=True, config=STRICT)
class Signals:
    """The hardware signals of a part: what it sends, and what it accepts."""

    outputs: dict[str, OutSignal] = field(default_factory=dict)
    inputs: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _named_as_in_the_file(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        if not isinstance(data, Mapping) or not {"out", "in"} & set(data):
            return data
        renamed = {"out": "outputs", "in": "inputs"}
        return {renamed.get(key, key): value for key, value in data.items()}


@dataclass(frozen=True, config=STRICT)
class Component:
    """An entry of the components library: what a part is, and which signals it has."""

    spec: Annotated[str, Field(pattern=f"^{COMPONENT_SPEC}")]
    description: str
    element: Element
    signals: Signals = field(default_factory=Signals)


#: What each kind of element must be able to change, for the server to have a control for it, and
#: what its numbers mean to the optics.
_NEEDS_TUNES = {
    "sensor": {"exposure": "ms"},
    "point_detector": {"exposure": "ms"},  # exposure: to a scan, the time of a whole frame
}
#: What a tune of this name has to be in, wherever one is stated; what has no tune is fixed.
_TUNE_UNITS = {"power": "mW", "exposure": "ms", "gain": "dB", "binning": "", "frame_rate": "Hz"}


@dataclass(frozen=True, config=STRICT, kw_only=True)
class Cube:
    """Housing around an optical element, and what its actuators do to it."""

    # Its key in the description: an identifier, so that a view can bind what it holds.
    name: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
    component: str | None = None  # the library entry its element and signals came from
    element: Element | None = None
    signals: Signals = field(default_factory=Signals)
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
            needs = _NEEDS_TUNES.get(self.element.kind, {})
            missing = set(needs) - set(self.tunes)
            if missing:
                raise ValueError(f"a {self.element.kind} must tune {sorted(missing)}")
            for name, unit in _TUNE_UNITS.items():
                if name in self.tunes and self.tunes[name].unit != unit:
                    raise ValueError(
                        f"{name} is in {unit or 'no unit'}, not {self.tunes[name].unit or 'no unit'}"
                    )
        for move in self.moves.values():
            if move.unit != "um":
                raise ValueError(f"{move.name} moves in a length, not {move.unit or 'no unit'}")
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
    side: Literal["epi", "transmitted", "orthogonal"] | None = None
    distance: Millimetres | Literal["focus"] | None = None  # or the lens's own focal length
    along: Literal["x", "y"] | None = None  # which way of the image a sheet travels
    field: Millimetres | None = None  # how wide the light lands on the sample; a sheet, how high

    @model_validator(mode="after")
    def _a_sheet_travels(self) -> Self:
        if (self.side == "orthogonal") != (self.along is not None):
            raise ValueError("a sheet has side: orthogonal and along, and only a sheet has them")
        return self


@dataclass(frozen=True, config=STRICT)
class Drive:
    """A wire: one part's signal driving another's input, such as ``camera.frame`` to ``stage.z``."""

    source: str = Field(validation_alias="from")
    target: str = Field(validation_alias="to")
    by: Micrometres | None = None  # how far each event steps a move

    @property
    def sender(self) -> tuple[str, str]:
        """The cube sending, and its signal."""
        cube, _, signal = self.source.rpartition(".")
        return cube, signal

    @property
    def receiver(self) -> tuple[str, str]:
        """The cube receiving, and its input."""
        cube, _, signal = self.target.rpartition(".")
        return cube, signal


@dataclass(frozen=True)
class DetectorAxis:
    """One axis a logical detector delivers: a physical detector and what is wired to it."""

    name: str
    size: int | None  # None: set per acquisition
    step: float | None  # in the unit of what delivers it
    delivered_by: str


@dataclass(frozen=True, config=STRICT, kw_only=True)
class Instrument:
    """A whole ``microscope.yml``: only ever read. `load` adds where it is."""

    folder: Path
    spec: Annotated[str, Field(pattern=f"^{SPEC}")]
    name: str
    cubes: dict[str, Cube]
    illumination: tuple[Edge, ...]
    detection: tuple[Edge, ...]
    settings: Settings
    drives: tuple[Drive, ...] = ()
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
        simulations = self.sample_holder().simulations
        problems = (
            []
            if self.settings.simulation in simulations
            else [
                f"settings.simulation: {self.settings.simulation!r} is none of the simulations "
                f"{sorted(simulations)}"
            ]
        )
        problems += [
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
        problems += _hardware_problems(self)
        problems += _drive_problems(self)
        problems += _sheet_problems(self)
        problems += _lit_problems(self)
        problems += _objective_problems(self)
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
        """Every variable at its initial value, and the simulation the settings name."""
        return {
            **{name: variable.initial for name, variable in self.variables.items()},
            self.simulation_key(): self.settings.simulation,
        }

    def swap_states(self) -> Iterator[dict[str, Any]]:
        """Every simulation under every combination of what the swaps can put in place.

        The rest is at its initial value.
        """
        swaps = [variable for variable in self.variables.values() if variable.verb == "swaps"]
        for simulation in self.sample_holder().simulations:
            for values in itertools.product(*(list(v.slots) for v in swaps)):
                yield {
                    **self.initial_state(),
                    self.simulation_key(): simulation,
                    **{v.name: value for v, value in zip(swaps, values)},
                }

    def detectors(self) -> list[str]:
        """The cubes of the detectors, in the order they are described."""
        return self._holding(Sensor, PointDetector)

    def sources(self) -> list[str]:
        """The cubes of the light sources, in the order they are described."""
        return self._holding(Source)

    def _holding(self, *kinds: type) -> list[str]:
        return [
            name
            for name, cube in self.cubes.items()
            if isinstance(cube.element, kinds)
            or any(
                isinstance(element, kinds)
                for swap in cube.swaps.values()
                for element in swap.slots.values()
            )
        ]

    def sample_cube(self) -> str:
        """The cube holding the sample."""
        return next(
            cube.name
            for cube in self.cubes.values()
            if cube.element is not None and cube.element.kind == "sample"
        )

    def sample_holder(self) -> SampleHolder:
        """The element holding the sample."""
        element = self.cubes[self.sample_cube()].element
        assert isinstance(element, SampleHolder)
        return element

    def simulation_key(self) -> str:
        """Where a state says what is on the holder: ``"stage.simulation"``. No variable changes it."""
        return f"{self.sample_cube()}.simulation"

    def simulation_at(self, state: Mapping[str, Any]) -> Simulation:
        """What is on the holder under `state`."""
        return self.sample_holder().simulations[state[self.simulation_key()]]

    def scanner_of(self, detector: str) -> str | None:
        """The cube whose events walk `detector` through an image, if there is one."""
        for drive in self.drives:
            cube, signal = drive.sender
            if drive.receiver[0] == detector and self.cubes[cube].signals.outputs[signal].axes:
                return cube
        return None

    def z_drive(self, detector: str) -> Drive | None:
        """The wire through which the events of `detector`, or of its scan, step the stage's z."""
        senders = (detector, self.scanner_of(detector))
        for drive in self.drives:
            target = self.variables.get(drive.target)
            if drive.sender[0] in senders and getattr(target, "along", None) == "axis":
                return drive
        return None

    def detector_axes(self, detector: str) -> tuple[DetectorAxis, ...]:
        """What the logical detector `detector` delivers, in the order of a dataset's axes."""
        element = self.cubes[detector].element
        found = []
        if isinstance(element, Sensor) and element.colors:
            found.append(DetectorAxis("c", len(element.colors), None, f"{detector}.colors"))
        if isinstance(element, PointDetector) and element.axes:
            bins = element.axes["microtime"]
            found.append(DetectorAxis("m", bins.size, bins.step, detector))
        stepped = self.z_drive(detector)
        if stepped is not None:
            found.append(
                DetectorAxis("z", None, stepped.by, f"{stepped.source} -> {stepped.target}")
            )
        scanner = self.scanner_of(detector)
        if scanner is None:
            assert isinstance(element, Sensor)
            found += [
                DetectorAxis(name, element.axes[name].size, element.axes[name].pitch, detector)
                for name in ("y", "x")
            ]
        else:
            axes = self.cubes[scanner].element.axes
            found += [
                DetectorAxis(name, axes[name].size, axes[name].step, scanner) for name in ("y", "x")
            ]
        return tuple(found)

    def edges_to(self, detector: str, sources: Iterable[str] | None = None) -> list[Edge]:
        """Every edge light takes to `detector`: from `sources` to the sample, and on from there."""
        sample = self.sample_cube()
        routes = [
            route
            for source in (self.sources() if sources is None else sources)
            for route in self.routes(self.illumination, source, sample)
        ] + self.routes(self.detection, sample, detector)
        return list(dict.fromkeys(edge for route in routes for edge in route))

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


def _hardware_problems(instrument: Instrument) -> list[str]:
    """What its ``hardware`` section names that the description does not have."""
    named = {variable.actuator for variable in instrument.variables.values()}
    problems = [
        f"hardware: no variable has the actuator {name!r}"
        for name in instrument.hardware.actuators
        if name not in named
    ]
    problems += [
        f"{variable.name}: hardware.actuators has no {variable.actuator!r}"
        for variable in instrument.variables.values()
        if variable.actuator is not None and variable.actuator not in instrument.hardware.actuators
    ]
    problems += [
        f"hardware: there is no sensor {name!r} for a camera"
        for name in instrument.hardware.cameras
        if not isinstance(_element(instrument, name), Sensor)
    ]
    return problems


def _element(instrument: Instrument, name: str) -> Element | None:
    """The one element of a cube, when `name` is a cube that has one."""
    cube = instrument.cubes.get(name)
    return None if cube is None else cube.element


def _scan_problems(instrument: Instrument) -> list[str]:
    """What is wrong with the point detectors, and the scans that make their images."""
    problems = []
    for detector in instrument.detectors():
        if not isinstance(_element(instrument, detector), PointDetector):
            continue
        scans = [
            drive
            for drive in instrument.drives
            if drive.receiver[0] == detector
            and instrument.cubes[drive.sender[0]].signals.outputs[drive.sender[1]].axes
        ]
        if len(scans) != 1:
            problems.append(
                f"{detector}: a point detector needs one scan wired to it, not {len(scans)}"
            )
            continue
        scanner = scans[0].sender[0]
        if not isinstance(_element(instrument, scanner), Scanner):
            problems.append(f"{scans[0].source}: only a scanner walks a detector through an image")
            continue
        routes = instrument.routes(instrument.illumination, scanner, instrument.sample_cube())
        if len(routes) != 1:
            problems.append(
                f"{scanner}: {len(routes)} illumination routes to the sample; one is handled"
            )
            continue
        problems += [
            f"{edge.source} -> {edge.target}: a scan's route needs the distance"
            for edge in routes[0]
            if edge.distance is None
        ]
        lenses = [
            element
            for edge in routes[0]
            if isinstance(element := _element(instrument, edge.target), Lens)
        ]
        if not lenses or lenses[-1].na is None or any(lens.f is None for lens in lenses):
            problems.append(f"{scanner}: a scan's lenses need f, and the last one its na")
    return problems


def _sheet_problems(instrument: Instrument) -> list[str]:
    """What is wrong with the light sheets: where one comes from says how thin it is."""
    problems = []
    sheets = [edge for edge in instrument.illumination if edge.side == "orthogonal"]
    for edge in sheets:
        lens = _element(instrument, edge.source)
        if not isinstance(lens, Lens) or lens.na is None:
            problems.append(f"{edge.source}: a sheet comes from a lens with its na")
    sample = instrument.sample_cube()
    for source in instrument.sources():
        routes = instrument.routes(instrument.illumination, source, sample)
        if sum(1 for route in routes if route[-1].side == "orthogonal") > 1:
            problems.append(f"{source}: one sheet per source is handled")
    return problems


def _microtime_problems(instrument: Instrument) -> list[str]:
    """What is wrong with the detectors timing their photons: the pulse they time them from."""
    problems = []
    for detector in instrument.detectors():
        element = _element(instrument, detector)
        if not isinstance(element, PointDetector) or not element.axes:
            continue
        syncs = [drive for drive in instrument.drives if drive.target == f"{detector}.sync"]
        if len(syncs) != 1:
            problems.append(
                f"{detector}: arrival times need one wire to its sync, not {len(syncs)}"
            )
        else:
            source = _element(instrument, syncs[0].sender[0])
            rate = source.repetition if isinstance(source, Source) else None
            window = element.axes["microtime"].size * element.axes["microtime"].step
            if rate is None:
                problems.append(f"{syncs[0].source}: its source needs a repetition")
            elif window > 1e12 / rate:
                problems.append(
                    f"{detector}: a window of {window:g} ps does not fit in a pulse period of "
                    f"{1e12 / rate:g} ps"
                )
        problems += [
            f"{detector}: the simulation {name!r} needs its fluorophore's lifetime"
            for name, simulation in instrument.sample_holder().simulations.items()
            if simulation.fluorophore is not None and simulation.fluorophore.lifetime is None
        ]
    return problems


def _objective_problems(instrument: Instrument) -> list[str]:
    """Each lens that can be the nearest to the sample on the way to a detector: how much it gathers
    is how bright an image is, and that takes its NA."""
    problems = set()
    sample = instrument.sample_cube()
    for detector in instrument.detectors():
        for route in instrument.routes(instrument.detection, sample, detector):
            for edge in route:
                cube = instrument.cubes[edge.target]
                elements = [
                    (f"{swap.name}: slot {slot}", element)
                    for swap in cube.swaps.values()
                    for slot, element in swap.slots.items()
                ] or [(f"cubes.{cube.name}", cube.element)]
                lenses = [(where, e) for where, e in elements if isinstance(e, Lens)]
                problems |= {
                    f"{where}: the lens nearest the sample needs its na"
                    for where, lens in lenses
                    if lens.na is None
                }
                if lenses:
                    break
    return sorted(problems)


def _lit_problems(instrument: Instrument) -> list[str]:
    """How much of the sample each source lights: it decides how bright a pixel is."""
    problems = []
    sample = instrument.sample_cube()
    for source in instrument.sources():
        for route in instrument.routes(instrument.illumination, source, sample):
            scanned = any(isinstance(_element(instrument, e.target), Scanner) for e in route)
            if not scanned and route[-1].field is None:
                problems.append(
                    f"{route[-1].source} -> {route[-1].target}: light lands on the sample here, "
                    "so it needs its field"
                )
    return problems


def _drive_problems(instrument: Instrument) -> list[str]:
    """What its ``drives`` section connects that the parts do not have."""
    problems = []
    moved: list[str] = []
    scanners = [
        drive.sender[0]
        for drive in instrument.drives
        if drive.sender[0] in instrument.cubes
        and drive.sender[1] in instrument.cubes[drive.sender[0]].signals.outputs
        and instrument.cubes[drive.sender[0]].signals.outputs[drive.sender[1]].axes
    ]
    for drive in instrument.drives:
        name, signal = drive.sender
        sender = instrument.cubes.get(name)
        if sender is None or signal not in sender.signals.outputs:
            problems.append(f"drives: {name!r} sends no signal {signal!r}")
        elif sender.signals.outputs[signal].axes and not isinstance(
            _element(instrument, drive.receiver[0]), PointDetector
        ):
            problems.append(f"drives: {drive.source} can only walk a point detector")
        name, signal = drive.receiver
        receiver = instrument.cubes.get(name)
        if receiver is None or signal not in receiver.signals.inputs:
            problems.append(f"drives: {name!r} accepts no signal {signal!r}")
            continue
        if signal not in receiver.moves:
            if drive.by is not None:
                problems.append(f"drives: {drive.target} moves nothing, so it takes no 'by'")
            continue
        moved.append(drive.target)
        if drive.by is None:
            problems.append(f"drives: {drive.target} is a move, so it needs 'by'")
        if instrument.variables[drive.target].along != "axis":
            problems.append(
                f"drives: only a move along the axis can be stepped, not {drive.target}"
            )
        elif drive.sender[0] not in (*instrument.detectors(), *scanners):
            problems.append(f"drives: {drive.source} is no detector, so it cannot deliver z")
    problems += [
        f"drives: {name} is stepped by two wires" for name in set(moved) if moved.count(name) > 1
    ]
    # Only once every wire connects something: this follows them.
    return problems or _scan_problems(instrument) + _microtime_problems(instrument)


def component_names() -> list[str]:
    """The entries of the components library."""
    return sorted(path.stem for path in COMPONENTS.glob("*.yml"))


def component_data(name: str) -> dict[str, Any]:
    """What an entry of the components library states, once it has validated.

    Raises:
        SpecError: There is no such entry, or it does not validate.
    """
    if name not in component_names():
        raise SpecError(f"there is no component {name!r}: there are {component_names()}")
    data = yaml.safe_load((COMPONENTS / f"{name}.yml").read_text())
    try:
        TypeAdapter(Component).validate_python(data)
    except ValidationError as exc:
        raise SpecError(f"component {name}: " + "; ".join(problems_of(exc))) from exc
    return data


def _with_components(data: Mapping[str, Any]) -> dict[str, Any]:
    """`data` with what the components it names state.

    Raises:
        SpecError: A cube names no entry, or states what its entry already does. Every such
            problem is listed; the rest of the description is looked at once these are fixed.
    """
    if not isinstance(data.get("cubes"), Mapping):
        return dict(data)
    cubes = {}
    problems = []
    for name, cube in data["cubes"].items():
        if not isinstance(cube, Mapping) or "component" not in cube:
            cubes[name] = cube
            continue
        stated = sorted({"element", "signals", "swaps"} & set(cube))
        if stated:
            problems.append(f"cubes.{name}: its component already states {stated}")
        try:
            entry = component_data(cube["component"])
        except SpecError as exc:
            problems.append(f"cubes.{name}: {exc}")
            continue
        cubes[name] = {**cube, "element": entry["element"], "signals": entry.get("signals", {})}
    if problems:
        raise SpecError("; ".join(problems))
    return {**data, "cubes": cubes}


def _with_view_files(data: dict[str, Any], folder: Path) -> dict[str, Any]:
    """`data`, with each blok that names a `file` holding what that file says.

    A blok names one explicitly, relative to its description, so that instruments can share a view
    without anything being found by its name.

    Raises:
        SpecError: A file does not exist, or a blok is written out and names one.
    """
    found = dict(data)
    problems = []
    for section in ("ui", "agent_ui"):
        if not isinstance(data.get(section), Mapping) or not isinstance(
            data[section].get("bloks"), Mapping
        ):
            continue
        bloks = {}
        for name, entry in data[section]["bloks"].items():
            if not isinstance(entry, Mapping) or "file" not in entry:
                bloks[name] = entry
                continue
            where = f"{section}.bloks.{name}"
            if "bsx" in entry:
                problems.append(f"{where}: a blok is written out or names a file, not both")
                continue
            view = folder / str(entry["file"])
            if not view.is_file():
                problems.append(f"{where}.file: {view} does not exist")
                continue
            rest = {key: value for key, value in entry.items() if key != "file"}
            bloks[name] = {**rest, "bsx": view.read_text()}
        found[section] = {**data[section], "bloks": bloks}
    if problems:
        raise SpecError("; ".join(problems))
    return found


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
    data = _with_view_files(_with_components(data), path.parent)
    try:
        return _INSTRUMENT.validate_python({**data, "folder": path.parent.resolve()})
    except ValidationError as exc:
        raise SpecError(f"{path}: " + "; ".join(problems_of(exc))) from exc
