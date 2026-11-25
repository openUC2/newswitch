"""The microscope as the designer describes it: cubes, their elements, and how light connects them.

An instrument is a folder: its description (``microscope.yml``) and the optics files it names. A
server computes what it does when it starts (`newswitch.instrument.compiler`), and runs from it directly
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
#: What an entry of the library of holders (``holders/``) states it is.
HOLDER_SPEC = "newswitch/holder/"

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
    depth: Annotated[Micrometres, Field(gt=0.0)]  # a section is thin, a volume is not: none is flat
    extent: Millimetres = 6.0  # how wide all of the slide is
    resolution: Micrometres = 2.0  # how finely it is rendered
    darkens: Fraction = 0.6  # how much of what passes straight through a bead takes


@dataclass(frozen=True, config=STRICT)
class Stain:
    """What takes up light passing through it, of some colors more than others, and where it is."""

    center: Nanometres  # what it takes up most of
    width: Nanometres
    darkens: Fraction  # how much of that, where there is most of it
    pattern: Pattern


@dataclass(frozen=True, config=STRICT)
class Electrical:
    """What the beads do electrically, as cells: each fires at random, `rate` times a second on
    average, and an electrode `reach` away picks up 1/e of `amplitude` (in microvolts)."""

    rate: Hertz
    amplitude: Annotated[StrictFloat, Field(gt=0.0)]
    reach: Annotated[Micrometres, Field(gt=0.0)]


@dataclass(frozen=True, config=STRICT)
class Simulation:
    """One thing that can be on the holder: without a fluorophore, it emits nothing.

    `absorbed` is the share of the light at its excitation peak that a bead on the path takes up.
    """

    transmit: Fraction  # light going straight through (transmitted light)
    reflect: Fraction  # light coming back the way it came (epi)
    pattern: Pattern | None = None  # its beads; None: none
    slide: SimulatedSlide | None = None
    """An opaque slide with holes lying on the mounted holder (a calibration slide): transmitted
    light passes only through its holes."""
    fluorophore: Annotated[Fluorophore, BeforeValidator(_from_library("fluorophores"))] | None = (
        None
    )
    absorbed: Fraction | None = None
    stains: dict[str, Stain] = field(default_factory=dict)
    electrical: Electrical | None = None  # whether its beads fire, as cells do

    @model_validator(mode="after")
    def _absorbs_what_it_emits(self) -> Self:
        if (self.fluorophore is None) != (self.absorbed is None):
            raise ValueError("a fluorophore and how much it absorbed come together")
        return self

    @model_validator(mode="after")
    def _is_something(self) -> Self:
        if self.pattern is None and self.slide is None:
            raise ValueError("a simulation has beads (pattern) or a slide, or both")
        return self


@dataclass(frozen=True, config=STRICT)
class Extent:
    """How far something goes along x and y."""

    x: Annotated[Millimetres, Field(gt=0.0)]
    y: Annotated[Millimetres, Field(gt=0.0)]


@dataclass(frozen=True, config=STRICT)
class Offset:
    """Where something is along x and y, from an origin."""

    x: Millimetres
    y: Millimetres


@dataclass(frozen=True, config=STRICT)
class Place:
    """One place of a grid, a well or an electrode: round, of a diameter, or square, of a size."""

    diameter: Annotated[Millimetres, Field(gt=0.0)] | None = None
    size: Annotated[Millimetres, Field(gt=0.0)] | None = None

    @model_validator(mode="after")
    def _one_shape(self) -> Self:
        if (self.diameter is None) == (self.size is None):
            raise ValueError("a place has a diameter or a size: exactly one of them")
        return self


@dataclass(frozen=True, config=STRICT)
class Grid:
    """Places in rows (A, B, ...) and columns (1, 2, ...), a pitch apart, A1's middle at `a1`: a
    plate's wells, an electrode array's electrodes."""

    rows: Annotated[StrictInt, Field(gt=0, le=26)]
    columns: Annotated[StrictInt, Field(gt=0)]
    pitch: Offset
    a1: Offset
    place: Place

    def places(self) -> dict[str, tuple[float, float]]:
        """Every place's middle by name (``"B3"``), in millimetres from the holder's origin."""
        return {
            f"{chr(ord('A') + row)}{column + 1}": (
                self.a1.x + column * self.pitch.x,
                self.a1.y + row * self.pitch.y,
            )
            for row in range(self.rows)
            for column in range(self.columns)
        }


@dataclass(frozen=True, config=STRICT)
class Holder:
    """An entry of the library of holders: what a sample is mounted on, and where its places are.

    Its origin is its top left corner, x to the right and y down, as a plate's A1 is counted. Its
    `grids` name its places, by kind: a plate's ``well``, an electrode array's ``electrode``.
    """

    spec: Annotated[str, Field(pattern=f"^{HOLDER_SPEC}")]
    description: str
    kind: Literal["slide", "dish", "plate", "mea"]
    extent: Extent
    grids: dict[str, Grid] = field(default_factory=dict)

    @model_validator(mode="after")
    def _a_plate_has_wells(self) -> Self:
        if self.kind == "plate" and "well" not in self.grids:
            raise ValueError("a plate has its wells (grids: {well: ...})")
        if self.kind == "mea" and "electrode" not in self.grids:
            raise ValueError("an electrode array has its electrodes (grids: {electrode: ...})")
        return self


@dataclass(frozen=True, config=STRICT)
class SimulatedSlide:
    """A slide from the library lying centred in a place of the mounted holder, opaque but for
    its places, which are holes: what a simulated pinhole slide is. Light passing straight
    through the sample passes only there."""

    holder: Annotated[Holder, BeforeValidator(_from_library("holders"))]
    at: str
    """The place of the mounted holder it lies in: ``<grid>:<name>``, as ``slot:A1``."""

    def holes(self) -> list[tuple[float, float, float]]:
        """Its holes from its middle, in millimetres, as ``(x, y, radius)``."""
        found = []
        for grid in self.holder.grids.values():
            radius = (grid.place.diameter or grid.place.size or 0.0) / 2.0
            for x, y in grid.places().values():
                found.append((x - self.holder.extent.x / 2, y - self.holder.extent.y / 2, radius))
        return found


@dataclass(frozen=True, config=STRICT)
class Mount:
    """Where a holder's origin sits on the stage of this instrument, and how far it is turned."""

    x: Millimetres
    y: Millimetres
    rotation: Degrees = 0.0

    @classmethod
    def of(cls, x_mm: float, y_mm: float, rotation_deg: float = 0.0) -> Mount:
        """A mount from numbers: millimetres, and degrees."""
        return cls(x=f"{x_mm!r} mm", y=f"{y_mm!r} mm", rotation=f"{rotation_deg!r} deg")  # type: ignore[arg-type]


@dataclass(frozen=True, config=STRICT)
class MountedHolder:
    """A holder this instrument takes, from the library by name, and where it sits when mounted."""

    holder: Annotated[Holder, BeforeValidator(_from_library("holders"))]
    mount: Mount


def place_of(holder: Holder, place: str, what: str) -> tuple[float, float]:
    """Where `place` (``"<grid>:<name>"``, as ``slot:A1``) of `holder` is, in millimetres from its
    origin.

    Raises:
        ValueError: It has no such place.
    """
    grid, _, name = place.partition(":")
    places = holder.grids[grid].places() if grid in holder.grids else {}
    if name not in places:
        known = sorted(f"{g}:{n}" for g, found in holder.grids.items() for n in found.places())
        raise ValueError(f"{what}: {place!r} is no place of it; it has {known}")
    return places[name]


@dataclass(frozen=True, config=STRICT)
class Calibration:
    """How the mount of a holder is measured: a calibration slide, centred in a place of the
    holder, and a mark on it that can be found in an image.

    Where the mark is on the stage when it is in the middle of `detector`'s image, less where it is
    on the holder (`mark_on_holder`), is where the holder's origin is: its mount.
    """

    holder: str
    """Which of the sample's holders it lies in."""
    at: str
    """The place of that holder it lies in, centred: ``<grid>:<name>``, as ``slot:A1``."""
    slide: Annotated[Holder, BeforeValidator(_from_library("holders"))]
    """The calibration slide, from the library of holders, or as stated."""
    mark: str
    """What is found of it: a place of the slide, ``<grid>:<name>``, as ``pinhole:B1``."""
    detector: str | None = None
    """What looks for it; by default the first detector of the sample."""
    home: list[Literal["X", "Y", "Z", "A"]] = field(default_factory=list)
    """The axes homed first, in this order, on the board that drives them."""
    values: dict[str, str] = field(default_factory=dict)
    """What the variables are taken to meanwhile, as quantities (``led.power: 20 nW``,
    ``stage.z: -3520 um``); each is taken back afterwards, but the stage's x and y."""
    search_radius: Millimetres = 4.0
    """How far from where the mount puts it the mark is looked for."""
    search_step: Millimetres = 1.0
    """How far apart the places looked at are: less than the image is wide."""

    def mark_on_slide(self) -> tuple[float, float]:
        """The mark from the slide's middle, in millimetres."""
        x, y = place_of(self.slide, self.mark, "mark")
        return x - self.slide.extent.x / 2, y - self.slide.extent.y / 2


@dataclass(frozen=True, config=STRICT)
class SampleHolder:
    """Where a sample is, and what can be on it, by name: `simulation` is the one that is.

    An instrument may have several, each a sample of its own, on a stage of its own, seen through
    light paths of its own (`Instrument.samples`). `holders` are what it can be mounted on, by name;
    `mounted` is the one it starts with. Without any, the sample's frame is its stage's.
    """

    kind: Literal["sample"]
    simulation: str
    simulations: Annotated[dict[str, Simulation], Field(min_length=1)]
    depth: Annotated[Micrometres, Field(gt=0.0)] | None = None
    """How deep a sample it takes: a section is thin (none: thin), a volume is not. Where in it a
    light sheet or a focus lands (`Instrument.lit_um`). What a simulation draws is the
    simulator's alone; nothing the optics predict depends on it."""
    holders: dict[str, MountedHolder] = field(default_factory=dict)
    mounted: str | None = None
    calibration: Calibration | None = None
    """How the mount of one of its holders is measured (`calibrate_mount`)."""

    def mark_on_holder(self) -> tuple[float, float]:
        """Where the calibration's mark is on its holder, in millimetres from the holder's origin,
        when the slide lies centred in its place."""
        assert self.calibration is not None
        calibration = self.calibration
        holder = self.holders[calibration.holder].holder
        x, y = place_of(holder, calibration.at, "at")
        dx, dy = calibration.mark_on_slide()
        return x + dx, y + dy

    @model_validator(mode="after")
    def _simulation_is_one_of_them(self) -> Self:
        if self.simulation not in self.simulations:
            raise ValueError(
                f"simulation: {self.simulation!r} is none of the simulations "
                f"{sorted(self.simulations)}"
            )
        return self

    @model_validator(mode="after")
    def _mounted_is_one_of_them(self) -> Self:
        if self.mounted is not None and self.mounted not in self.holders:
            raise ValueError(
                f"mounted: {self.mounted!r} is none of the holders {sorted(self.holders)}"
            )
        if self.holders and self.mounted is None:
            raise ValueError("with holders, one is mounted to start with (mounted:)")
        return self

    @model_validator(mode="after")
    def _slides_lie_in_the_mounted_holder(self) -> Self:
        for name, simulation in self.simulations.items():
            if simulation.slide is None:
                continue
            if self.mounted is None:
                raise ValueError(f"simulations: {name}: a slide lies in a holder, and none is mounted")
            place_of(self.holders[self.mounted].holder, simulation.slide.at, f"simulations: {name}: at")
        return self

    @model_validator(mode="after")
    def _calibration_is_in_one_of_them(self) -> Self:
        calibration = self.calibration
        if calibration is None:
            return self
        if calibration.holder not in self.holders:
            raise ValueError(
                f"calibration: holder {calibration.holder!r} is none of the holders "
                f"{sorted(self.holders)}"
            )
        place_of(self.holders[calibration.holder].holder, calibration.at, "calibration: at")
        calibration.mark_on_slide()
        return self


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
class Mirror:
    """Reflects all of the light and lets none through: in a swap, with an open slot beside it, a
    flip mirror, which sends the light one way or the other."""

    kind: Literal["mirror"]
    name: str | None = None


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


@dataclass(frozen=True, config=STRICT)
class StagePoint:
    """A point on a stage insert, in its stage's coordinates: it moves with that stage, so with its
    sample. `stage` names the sample cube whose stage it is on; it may be left out when there is one."""

    x: Millimetres
    y: Millimetres
    z: Millimetres = 0.0
    stage: str | None = None


@dataclass(frozen=True, config=STRICT)
class Measures:
    """What a probe measures, as words: the quantity and its unit (``voltage``, ``uV``)."""

    quantity: str
    unit: str = ""


@dataclass(frozen=True, config=STRICT)
class ProbeModel:
    """How a simulated probe reads: which of the simulator's models, and how far a reading strays,
    in the probe's unit. A real one is read by a driver."""

    kind: Literal["air", "spikes"]
    noise: Annotated[StrictFloat, Field(ge=0.0)] = 0.0


@dataclass(frozen=True, config=STRICT)
class GridRead:
    """The places of a grid a probe reads at: `grid` of what `sample` is mounted on (an electrode
    array's ``electrode``); `sample` may be left out when there is one."""

    grid: str
    sample: str | None = None


@dataclass(frozen=True, config=STRICT)
class Sampling:
    """How a probe samples time: `rate` samples a second, read in blocks `block` long."""

    rate: Hertz
    block: Annotated[StrictFloat, Field(gt=0.0), BeforeValidator(_in_unit("ms"))]

    @property
    def samples(self) -> int:
        """How many samples a block has."""
        return max(1, round(self.rate * self.block / 1000.0))


@dataclass(frozen=True, config=STRICT)
class Probe:
    """A detector of no light: it measures a quantity where it sits, light has nothing to do with it.

    It sits `at` a point on a stage insert, beside the sample, and moves with that stage; or it
    `reads` a grid of what the sample is mounted on (an electrode array's electrodes), and is where
    those are. With `sampling`, each reading is a block of samples in time. What a simulated one
    reads, its `model` says, and the simulator knows (`newswitch.simulation.simulator`).
    """

    kind: Literal["probe"]
    measures: Measures
    model: ProbeModel
    at: StagePoint | None = None
    reads: GridRead | None = None
    sampling: Sampling | None = None

    @model_validator(mode="after")
    def _sits_somewhere(self) -> Self:
        if (self.at is None) == (self.reads is None):
            raise ValueError("a probe sits at a point (at:) or reads a grid (reads:): exactly one")
        return self

    @property
    def sample(self) -> str | None:
        """The sample it sits beside or reads, where it says."""
        if self.at is not None:
            return self.at.stage
        assert self.reads is not None
        return self.reads.sample


#: An element: what it is, and the numbers that say what it does to light (or, a probe, not).
Element = Annotated[
    Source
    | Lens
    | SampleHolder
    | Sensor
    | Filter
    | Dichroic
    | Splitter
    | Mirror
    | Scanner
    | Pinhole
    | PointDetector
    | Probe,
    Field(discriminator="kind"),
]


def passes(element: Element | None, via: str | None) -> bool:
    """Whether any light leaves `element` the way `via` says: what a mirror reflects, what a
    splitter sends either way it sends any, both ways out of a dichroic, and through anything else.

    Only whether, never how much: that is the tracer's, wavelength by wavelength.
    """
    match element:
        case Mirror():
            return via == "reflect"
        case Splitter():
            return (element.reflect if via == "reflect" else element.transmit) > 0
        case Dichroic():
            return True
    return via != "reflect"


class Dark(ValueError):
    """A detector that no light reaches under the state asked about: a switch sends it elsewhere."""


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
        key: data[key]
        for key in ("initial", "step", "min", "max", "lit")
        if data.get(key) is not None
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
    lit: Number | None = None
    """A source's power, what it comes on at when nothing says otherwise (it was never on since
    the start, and an acquisition or a switch turns it on): its maximum when not stated."""
    unit: str = ""  # what its numbers are in, from how they are stated

    @model_validator(mode="before")
    @classmethod
    def _one_unit(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        return _in_one_unit(data)

    @model_validator(mode="after")
    def _starts_in_range(self) -> Self:
        _starts_in_range(self)
        if self.lit is not None and (
            self.lit <= 0 or (self.max is not None and self.lit > self.max)
        ):
            raise ValueError(f"lit {self.lit} is not a power it can come on at (0 < lit <= max)")
        return self


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
    # Where paths meet at a switch, the cube the light leaving this way came in from: what a flip
    # mirror lets through goes on one way, what it reflects comes from another.
    came_from: str | None = None

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


#: What an axis of a detector measures of the sample: where (``space``, placed by the coordinate
#: graph, `newswitch.instrument.space`), which colors, when a photon arrived after its pulse, or when.
Domain = Literal["space", "spectrum", "microtime", "time"]


@dataclass(frozen=True)
class DetectorAxis:
    """One axis a logical detector delivers: a physical detector and what is wired to it.

    It measures a domain of the sample. Which way a spatial one runs on the sample is not its to
    say: a turned sensor's x is some of the sample's x and some of its y. The coordinate graph says.
    """

    name: str
    size: int | None  # None: set per acquisition
    step: float | None  # in `unit`, native to what delivers it: a sensor's pitch, a scan's angle
    unit: str
    domain: Domain
    delivered_by: str
    binnable: bool = (
        False  # a sensor's own pixels bin; a scan's positions and a stage's planes do not
    )


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
        if not self.samples():
            raise ValueError("no cube holds the sample")
        problems = [
            f"an edge names no cube {name!r}"
            for edge in (*self.illumination, *self.detection)
            for name in (edge.source, edge.target)
            if name not in self.cubes
        ]
        if problems:
            raise ValueError("; ".join(problems))
        problems += [
            f"{edge.source} -> {edge.target}: came_from {edge.came_from!r} sends no light into "
            f"{edge.source}"
            for edge in (*self.illumination, *self.detection)
            if edge.came_from is not None
            and not any(
                other.source == edge.came_from and other.target == edge.source
                for other in (*self.illumination, *self.detection)
            )
        ]
        if problems:
            raise ValueError("; ".join(problems))
        seen_at_all: set[str] = set()
        for detector in self.detectors():
            if not self.samples_of(detector):
                problems.append(f"no light reaches {detector}")
                continue
            ever: set[str] = set()
            for state in self.switch_states(detector):
                seen = [
                    sample
                    for sample in self.samples_of(detector)
                    if self.open_routes(self.detection, sample, detector, state)
                ]
                if len(seen) > 1:
                    switches = ", ".join(
                        f"{name}={state[name]}" for name in self.switches_of(detector)
                    )
                    problems.append(
                        f"{detector} is reached from the samples {seen} at once"
                        + (f" with {switches}" if switches else "")
                        + ": a detector sees one sample at a time"
                    )
                    break
                ever.update(seen)
            else:
                if not ever:
                    problems.append(f"no light reaches {detector}, however its switches are set")
            seen_at_all |= ever
        if not problems:
            problems += [
                f"no detector sees {sample}, however the switches are set"
                for sample in self.samples()
                if sample not in seen_at_all
            ]
        for detector in self.detectors():
            drive = self.z_drive(detector)
            if drive is None or problems:
                continue
            owns = {
                sample: {
                    move.name for move in (*self.sample_moves(sample), *self.sheet_moves(sample))
                }
                for sample in self.samples_of(detector)
            }
            if not any(drive.target in own for own in owns.values()):
                problems.append(
                    f"{drive.source} -> {drive.target}: {detector} sees {sorted(owns)}, and its "
                    f"planes step what moves its sample or its sheet: "
                    f"{sorted(set().union(*owns.values()))}"
                )
        for probe in self.probes():
            element = self.cubes[probe].element
            assert isinstance(element, Probe)
            stage = element.sample
            if stage is None and len(self.samples()) > 1:
                problems.append(f"{probe}: it says which of the samples {self.samples()} it is of")
            elif stage is not None and stage not in self.samples():
                problems.append(f"{probe}: {stage!r} is none of the samples {self.samples()}")
            elif element.reads is not None:
                problems += self._grid_problems(probe, element.reads.grid)
        if problems:
            raise ValueError("; ".join(problems))
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

    def design_hash(self) -> str:
        """What a calibration of this microscope is of: a digest of everything it is built as
        (its parts, light paths, wiring and hardware, with what its library entries say), and
        not of how a run behaves (``settings``), its views (``ui``) or where its file lies. A
        calibration stored under another digest is of another design."""
        data = _INSTRUMENT.dump_python(self, mode="json")
        for key in ("settings", "ui", "folder"):
            data.pop(key, None)
        text = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()

    def initial_state(self) -> dict[str, Any]:
        """Every variable at its initial value."""
        return {name: variable.initial for name, variable in self.variables.items()}

    def swap_states(self) -> Iterator[dict[str, Any]]:
        """Every combination of what the swaps can put in place; the rest at its initial value."""
        swaps = [variable for variable in self.variables.values() if variable.verb == "swaps"]
        for values in itertools.product(*(list(v.slots) for v in swaps)):
            yield {**self.initial_state(), **{v.name: value for v, value in zip(swaps, values)}}

    def detectors(self) -> list[str]:
        """The cubes of the detectors of light, in the order they are described."""
        return self._holding(Sensor, PointDetector)

    def grid_of(self, probe: str) -> Grid:
        """The grid `probe` reads: as the holders of its sample that have it have it, alike."""
        element = self.cubes[probe].element
        assert isinstance(element, Probe) and element.reads is not None
        (sample,) = self.samples_of(probe)
        return next(
            mounted.holder.grids[element.reads.grid]
            for mounted in self.sample_holder(sample).holders.values()
            if element.reads.grid in mounted.holder.grids
        )

    def _grid_problems(self, probe: str, grid: str) -> list[str]:
        """What is wrong with the grid `probe` reads: none of its sample's holders has it, or two
        have it otherwise (its axes would change with what is mounted)."""
        (sample,) = self.samples_of(probe)
        grids = {
            name: mounted.holder.grids[grid]
            for name, mounted in self.sample_holder(sample).holders.items()
            if grid in mounted.holder.grids
        }
        if not grids:
            return [f"{probe}: no holder of {sample} has the grid {grid!r} it reads"]
        shapes = {(g.rows, g.columns, g.pitch) for g in grids.values()}
        if len(shapes) > 1:
            return [f"{probe}: the holders {sorted(grids)} of {sample} have {grid!r} grids unalike"]
        return []

    def probes(self) -> list[str]:
        """The cubes of the probes: detectors too, of no light (a thermometer, an electrode array)."""
        return self._holding(Probe)

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

    def samples(self) -> list[str]:
        """The cubes holding a sample, in the order they are described: each a stage of its own."""
        return [
            cube.name
            for cube in self.cubes.values()
            if cube.element is not None and cube.element.kind == "sample"
        ]

    def samples_of(self, detector: str) -> list[str]:
        """Every sample light gets to `detector` from, some way the switches can be set; a probe's,
        the one it sits beside."""
        element = self.cubes[detector].element if detector in self.cubes else None
        if isinstance(element, Probe):
            stage = element.sample
            if stage is not None:
                return [stage]
            (only,) = self.samples()
            return [only]
        states = list(self.switch_states(detector))
        return [
            sample
            for sample in self._routed(detector)
            if any(self.open_routes(self.detection, sample, detector, s) for s in states)
        ]

    def _routed(self, detector: str) -> list[str]:
        """Every sample a detection route goes from to `detector`, open or not."""
        return [
            sample for sample in self.samples() if self.routes(self.detection, sample, detector)
        ]

    def sample_of(self, detector: str, state: Mapping[str, Any]) -> str | None:
        """The sample `detector` measures under `state`: the one light gets to it from, the switches
        as `state` sets them; none, when they send its light elsewhere. A probe's is the one
        it sits beside, whatever the state.

        Raises:
            ValueError: Light gets to it from several samples at once.
        """
        if isinstance(self.cubes[detector].element, Probe):
            return self.samples_of(detector)[0]
        candidates = self._routed(detector)
        seen = [
            sample
            for sample in candidates
            if self.open_routes(self.detection, sample, detector, state)
        ]
        if len(seen) > 1:
            raise ValueError(f"{detector!r} sees {seen} at once")
        return seen[0] if seen else None

    def seen_sample(self, detector: str, state: Mapping[str, Any]) -> str:
        """The sample `detector` measures under `state`, which it must see.

        Raises:
            Dark: It sees none: the message says what to switch.
        """
        sample = self.sample_of(detector, state)
        if sample is None:
            raise self.dark(detector, state)
        return sample

    def dark(self, detector: str, state: Mapping[str, Any]) -> Dark:
        """Why `detector` sees nothing under `state`, and what to switch so that it does."""
        for other in self.switch_states(detector):
            if self.sample_of(detector, other) is not None:
                changes = ", ".join(
                    f"{name}={other[name]}"
                    for name in self.switches_of(detector)
                    if other[name] != state[name]
                )
                return Dark(f"No light reaches {detector}; with {changes} it does")
        return Dark(f"No light reaches {detector}")

    def switches_of(self, detector: str) -> list[str]:
        """The swaps on the way from any sample to `detector`: what can change where its light
        comes from, or whether any does."""
        cubes = {
            edge.source
            for sample in self._routed(detector)
            for route in self.routes(self.detection, sample, detector)
            for edge in route
        }
        return [
            swap.name
            for name, cube in self.cubes.items()
            if name in cubes
            for swap in cube.swaps.values()
        ]

    def switch_states(self, detector: str) -> Iterator[dict[str, Any]]:
        """Every way the switches on the way to `detector` can be set, the rest as they start."""
        names = self.switches_of(detector)
        variables = self.variables
        start = self.initial_state()
        for slots in itertools.product(*(list(variables[name].slots) for name in names)):
            yield {**start, **dict(zip(names, slots))}

    def detection_routes(self, detector: str, state: Mapping[str, Any]) -> list[tuple[Edge, ...]]:
        """The ways light goes from the sample `detector` sees under `state` to it.

        Raises:
            Dark: It sees none.
        """
        sample = self.seen_sample(detector, state)
        return self.open_routes(self.detection, sample, detector, state)

    def open_routes(
        self, edges: tuple[Edge, ...], start: str, end: str, state: Mapping[str, Any]
    ) -> list[tuple[Edge, ...]]:
        """The ways light goes from `start` to `end` along `edges` with the switches as `state`
        sets them: every element on the way lets it leave the way the next edge takes."""
        return [
            route
            for route in self.routes(edges, start, end)
            if all(passes(self.cubes[edge.source].element_at(state), edge.via) for edge in route)
        ]

    def samples_lit_by(self, source: str) -> list[str]:
        """The samples light from `source` lands on."""
        return [
            sample for sample in self.samples() if self.routes(self.illumination, source, sample)
        ]

    def sample_holder(self, sample: str) -> SampleHolder:
        """The element holding `sample`."""
        element = self.cubes[sample].element
        assert isinstance(element, SampleHolder), f"{sample!r} holds no sample"
        return element

    def sheet_moves(self, sample: str) -> list[Move]:
        """What moves a light sheet through `sample`: a move along the axis, of anything on the way
        to it."""
        cubes = {
            name
            for source in self.sources()
            for route in self.routes(self.illumination, source, sample)
            if route[-1].side == "orthogonal"
            for name in (source, *(edge.source for edge in route))
        }
        return [
            variable
            for name in sorted(cubes)
            for variable in self.cubes[name].variables.values()
            if variable.verb == "moves" and variable.along == "axis"
        ]

    def sample_moves(self, sample: str) -> list[Move]:
        """What moves `sample` along the axis."""
        return [
            variable
            for variable in self.cubes[sample].variables.values()
            if variable.verb == "moves" and variable.along == "axis"
        ]

    def lit_um(
        self,
        state: Mapping[str, Any],
        focus_um: float = 0.0,
        *,
        sample: str,
        depth_um: float | None = None,
    ) -> float:
        """Where the part of the sample that is seen is along the axis.

        The part nearest the plane the light makes of it: a sheet's, or else where the optics
        focus, having taken that `focus_um` towards the lens. So in a thin section it is where the
        section is and in a volume where the plane is, and no sample is treated differently for
        being either. How deep it is, its holder says (`SampleHolder.depth`), or `depth_um`.
        """
        depth = self.sample_holder(sample).depth if depth_um is None else depth_um
        half = (depth or 0.0) / 2.0  # with none stated, it is thin
        at = sum(float(state[move.name]) for move in self.sample_moves(sample))
        sheets = self.sheet_moves(sample)
        has_sheet = any(
            route[-1].side == "orthogonal"
            for source in self.sources()
            for route in self.routes(self.illumination, source, sample)
        )
        plane = sum(float(state[move.name]) for move in sheets) if has_sheet else -focus_um
        return min(max(plane, at - half), at + half)

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
        """What the logical detector `detector` delivers, in the order of a dataset's axes; a
        probe at a point delivers none."""
        element = self.cubes[detector].element
        if isinstance(element, Probe):
            found = []
            if element.sampling is not None:
                found.append(
                    DetectorAxis(
                        "s",
                        element.sampling.samples,
                        1000.0 / element.sampling.rate,
                        "ms",
                        "time",
                        detector,
                    )
                )
            if element.reads is not None:
                grid = self.grid_of(detector)
                found += [
                    DetectorAxis("y", grid.rows, grid.pitch.y * 1000.0, "um", "space", detector),
                    DetectorAxis("x", grid.columns, grid.pitch.x * 1000.0, "um", "space", detector),
                ]
            return tuple(found)
        found = []
        if isinstance(element, Sensor) and element.colors:
            found.append(
                DetectorAxis("c", len(element.colors), None, "", "spectrum", f"{detector}.colors")
            )
        if isinstance(element, PointDetector) and element.axes:
            bins = element.axes["microtime"]
            found.append(DetectorAxis("m", bins.size, bins.step, "ps", "microtime", detector))
        stepped = self.z_drive(detector)
        if stepped is not None:
            found.append(
                DetectorAxis(
                    "z", None, stepped.by, "um", "space", f"{stepped.source} -> {stepped.target}"
                )
            )
        scanner = self.scanner_of(detector)
        if scanner is None:
            assert isinstance(element, Sensor)
            found += [
                DetectorAxis(
                    name,
                    element.axes[name].size,
                    element.axes[name].pitch,
                    "um",
                    "space",
                    detector,
                    binnable=True,
                )
                for name in ("y", "x")
            ]
        else:
            axes = self.cubes[scanner].element.axes
            found += [
                DetectorAxis(name, axes[name].size, axes[name].step, "deg", "space", scanner)
                for name in ("y", "x")
            ]
        return tuple(found)

    def edges_to(
        self, detector: str, state: Mapping[str, Any], sources: Iterable[str] | None = None
    ) -> list[Edge]:
        """Every edge light takes to `detector` under `state`: from `sources` to the sample it sees,
        and on from there.

        Raises:
            Dark: It sees no sample under `state`.
        """
        sample = self.seen_sample(detector, state)
        routes = [
            route
            for source in (self.sources() if sources is None else sources)
            for route in self.open_routes(self.illumination, source, sample, state)
        ] + self.open_routes(self.detection, sample, detector, state)
        return list(dict.fromkeys(edge for route in routes for edge in route))

    def routes(self, edges: tuple[Edge, ...], start: str, end: str) -> list[tuple[Edge, ...]]:
        """Every way light can go from `start` to `end` along `edges`."""
        found: list[tuple[Edge, ...]] = []

        def walk(at: str, walked: tuple[Edge, ...]) -> None:
            if at == end:
                found.append(walked)
                return
            for edge in edges:
                if edge.source != at or edge in walked:
                    continue
                if edge.came_from is not None and (
                    not walked or walked[-1].source != edge.came_from
                ):
                    continue
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
        routes = [
            route
            for sample in instrument.samples_of(detector)
            for route in instrument.routes(instrument.illumination, scanner, sample)
        ]
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
    for source in instrument.sources():
        for sample in instrument.samples_lit_by(source):
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
    return problems


def _objective_problems(instrument: Instrument) -> list[str]:
    """Each lens that can be the nearest to the sample on the way to a detector: how much it gathers
    is how bright an image is, and that takes its NA."""
    problems = set()
    for detector in instrument.detectors():
        for route in (
            route
            for sample in instrument.samples_of(detector)
            for route in instrument.routes(instrument.detection, sample, detector)
        ):
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
    for source in instrument.sources():
        for route in (
            route
            for sample in instrument.samples_lit_by(source)
            for route in instrument.routes(instrument.illumination, source, sample)
        ):
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
    for section in ("ui",):
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
    if "agent_ui" in data:
        raise SpecError(
            f"{path}: agent_ui: the agent's bloks ship with newswitch (newswitch/infra/ui/agent/) "
            "and are the same on every microscope; remove the section"
        )
    data = _with_view_files(_with_components(data), path.parent)
    try:
        return _INSTRUMENT.validate_python({**data, "folder": path.parent.resolve()})
    except ValidationError as exc:
        raise SpecError(f"{path}: " + "; ".join(problems_of(exc))) from exc
