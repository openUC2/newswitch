"""What light does on its way: ray tracing for geometry, and transmission curves for colour.

The only module that imports optiland, and only when it traces: a scan needs no ray tracing, so an
instrument with nothing else never loads it. A server traces when it starts (`compiler`).

Each route is traced on its own, as a straight line with mirrors unfolded: optiland traces one
sequence of surfaces, and branching is the job of the routes. Filters and dichroics only shape the
spectrum here, as they are thin and flat, and a mirror only flips the image.

Every lens on a route, and the sensor it ends on, is placed where its moves put it before it is
traced: along the axis and across it (`_layout`). So what any of them does to where the image is,
how large and how sharp, is traced, and none of it is a case of its own. Across the axis, x and y
are the sensor's, carried back along the light.

Errors can be passed in (`Errors`), so the same tracer can describe a microscope that is not quite
what its description says. Nominal predictions pass none.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from newswitch.instrument.spec import (
    BandPass,
    Curve,
    Dichroic,
    Edge,
    Element,
    Filter,
    Instrument,
    Lens,
    LongPass,
    MultiBand,
    Neutral,
    Sensor,
    ShortPass,
    Source,
    Splitter,
    Table,
    passes,
)

#: Planck's constant times the speed of light, in joule metres.
_HC = 6.62607015e-34 * 299792458.0
#: How far past the outermost wavelength stated the spectrum goes, in nanometres: tails are small.
_MARGIN = 150.0


@dataclass(frozen=True)
class Errors:
    """How the real thing differs from its description, as far as optics can say."""

    objective_focal_factor: float = 1.0


@dataclass(frozen=True)
class Imaging:
    """What a route does to the sample's light, at the middle of its spectrum."""

    magnification: float  # signed: optics inverts, so this is negative
    reflections: int
    distortion_percent: float  # at the corner of the sensor
    relative_illumination: float  # rays getting through at the corner, against the centre
    spot_center_um: float  # rms, on the sensor
    spot_corner_um: float
    numerical_aperture: float  # on the sensor's side
    shift_x_um: float = 0.0  # where the middle of what is seen lands, from the sensor's middle
    shift_y_um: float = 0.0
    focus_um: float = 0.0  # how far the plane in focus is from where the sample starts, lens-wards


def _elements(instrument: Instrument) -> Iterator[Element]:
    """Every element of an instrument, also those only a swap puts in place."""
    for cube in instrument.cubes.values():
        if cube.element is not None:
            yield cube.element
        for swap in cube.swaps.values():
            yield from swap.slots.values()


def _curve_wavelengths(curve: Curve) -> list[float]:
    match curve:
        case BandPass():
            return [curve.center - curve.width, curve.center + curve.width]
        case LongPass() | ShortPass():
            return [curve.cut]
        case MultiBand():
            return [band.center for band in curve.bands]
        case Table():
            return [point[0] for point in curve.points]
    return []


def wavelengths(instrument: Instrument, extra: Iterable[float] = ()) -> np.ndarray:
    """The spectrum everything of `instrument` is computed on, in nanometres: what its parts
    state, and `extra` (what a simulated sample emits, for the simulator)."""
    stated: list[float] = []
    for element in _elements(instrument):
        match element:
            case Source():
                stated += [line.center for line in element.spectrum]
            case Filter(curve=curve) if curve is not None:
                stated += _curve_wavelengths(curve)
            case Dichroic():
                stated += _curve_wavelengths(element.curve)
            case Sensor():
                stated += [color.center for color in element.colors.values()]
    stated += list(extra)
    low = max(math.floor(min(stated, default=550.0) - _MARGIN), 1)
    high = math.ceil(max(stated, default=550.0) + _MARGIN)
    return np.arange(float(low), float(high) + 1.0, 1.0)


def gaussian(grid: np.ndarray, center: float, width: float) -> np.ndarray:
    """A line of full width at half maximum `width` around `center`, on `grid`; 1 at its peak."""
    return np.exp(-0.5 * ((grid - center) / (width / 2.355)) ** 2)


def curve_at(curve: Curve, grid: np.ndarray) -> np.ndarray:
    """How much of each wavelength a curve lets through."""
    match curve:
        case BandPass():
            passed = 1.0 / (
                1.0 + np.exp((np.abs(grid - curve.center) - curve.width / 2.0) / curve.edge)
            )
        case LongPass():
            passed = 1.0 / (1.0 + np.exp(-(grid - curve.cut) / curve.edge))
        case ShortPass():
            passed = 1.0 / (1.0 + np.exp((grid - curve.cut) / curve.edge))
        case MultiBand():
            passed = np.max(
                [
                    1.0
                    / (1.0 + np.exp((np.abs(grid - band.center) - band.width / 2.0) / curve.edge))
                    for band in curve.bands
                ],
                axis=0,
            )
        case Neutral():
            return np.full(grid.shape, curve.transmission)
        case Table():
            return np.interp(grid, *zip(*curve.points), left=0.0, right=0.0)
    passed = curve.peak * passed
    return passed if curve.od is None else np.maximum(passed, 10.0**-curve.od)


def transmission(element: Element, via: str | None, grid: np.ndarray) -> np.ndarray:
    """How much of each wavelength an element lets through, leaving the way `via` says."""
    match element:
        case Dichroic():
            through = curve_at(element.curve, grid)
            return through if via == "transmit" else 1.0 - through
        case Filter(curve=curve) if curve is not None and via != "reflect":
            return curve_at(curve, grid)
        case Splitter():
            return np.full(
                grid.shape, float(element.reflect if via == "reflect" else element.transmit)
            )
    return np.full(grid.shape, 1.0 if passes(element, via) else 0.0)


def _route_transmission(
    instrument: Instrument, route: tuple[Edge, ...], state: Mapping[str, Any], grid: np.ndarray
) -> np.ndarray:
    curve = np.ones(grid.shape)
    for edge in route:
        element = instrument.cubes[edge.source].element_at(state)
        curve = curve * transmission(element, edge.via, grid)
    return curve


def _objective(
    instrument: Instrument, routes: list[tuple[Edge, ...]], state: Mapping[str, Any]
) -> Lens:
    """The lens nearest the sample on the way to a detector."""
    for route in routes:
        for edge in route:
            element = instrument.cubes[edge.target].element_at(state)
            if isinstance(element, Lens):
                return element
    raise ValueError("no lens on the way from the sample")


def collected(lens: Lens) -> float:
    """The share of what a point emits, in all directions, that a lens gathers."""
    if lens.na is None:
        raise ValueError(f"{lens.name or 'a lens'} nearest the sample needs its na")
    return (1.0 - math.cos(math.asin(lens.na / lens.index))) / 2.0


def depth_of_field_um(instrument: Instrument, detector: str, state: Mapping[str, Any]) -> float:
    """How deep what a detector sees sharply is: wavelength x index / NA^2."""
    routes = instrument.detection_routes(detector, state)
    lens = _objective(instrument, routes, state)
    wavelength_um = design_wavelength(instrument, detector, state) / 1000.0
    return wavelength_um * lens.index / lens.na**2


def design_wavelength(instrument: Instrument, detector: str, state: Mapping[str, Any]) -> float:
    """The wavelength a route is traced at: what its filters pass, whatever is on the sample.

    So that what the optics predict for an instrument does not depend on a simulated sample. With
    no filter to say, it is what the first source lighting its sample emits; with none, the middle
    of the spectrum.
    """
    grid = wavelengths(instrument)
    stage = instrument.seen_sample(detector, state)
    for route in instrument.detection_routes(detector, state):
        filters = [
            element
            for edge in route
            if isinstance(element := instrument.cubes[edge.target].element_at(state), Filter)
            and element.curve is not None
        ]
        if filters:
            passed = np.prod([curve_at(element.curve, grid) for element in filters], axis=0)
            return float((passed * grid).sum() / passed.sum())
    sources = [s for s in instrument.sources() if stage in instrument.samples_lit_by(s)]
    if sources:
        return instrument.cubes[sources[0]].element_at(state).wavelength
    return float(grid[len(grid) // 2])


def _sheet(lens: Element, along: str, wavelength_nm: float) -> dict[str, Any]:
    """A light sheet as the Gaussian beam `lens` focuses: how thin it is, and for how far."""
    wavelength_um = wavelength_nm / 1000.0
    waist = wavelength_um / (math.pi * lens.na)
    return {
        "waist_um": waist,
        "rayleigh_um": math.pi * waist**2 * lens.index / wavelength_um,
        "along": along,
    }


@dataclass(frozen=True)
class Transfer:
    """What the optics do with one source's light on its way to a detector, whatever the sample:
    per milliwatt and millisecond, its photons landing on the sample by each route (with the side
    they land from), and what each way to the detector lets through."""

    lit: tuple[tuple[str | None, np.ndarray], ...]
    detection: tuple[np.ndarray, ...]
    qe: float
    gathered: float  # the share of what a point emits that the objective gathers
    colors: Mapping[str, np.ndarray]  # a color sensor's channels, each its band on the grid
    shape: Mapping[str, Any]  # a sheet, a field (field_um) or a spot


def transfer(
    instrument: Instrument, detector: str, state: Mapping[str, Any], grid: np.ndarray
) -> dict[str, Transfer]:
    """What every source's light goes through to reach `detector`, with nothing said of what it
    lands on: what the sample does is `couple`'s."""
    stage = instrument.seen_sample(detector, state)
    detection = instrument.detection_routes(detector, state)
    element = instrument.cubes[detector].element_at(state)
    colors = element.colors if isinstance(element, Sensor) else {}
    gathered = collected(_objective(instrument, detection, state))
    through = tuple(_route_transmission(instrument, edges, state, grid) for edges in detection)
    bands = {name: gaussian(grid, color.center, color.width) for name, color in colors.items()}
    found: dict[str, Transfer] = {}
    for source in instrument.sources():
        emitter = instrument.cubes[source].element_at(state)
        spectrum = np.sum(
            [gaussian(grid, line.center, line.width) for line in emitter.spectrum], axis=0
        )
        spectrum = spectrum / spectrum.sum()
        # photons per milliwatt and millisecond: a microjoule's worth, at its wavelength
        photons = 1e-6 * emitter.wavelength * 1e-9 / _HC
        lit: list[tuple[str | None, np.ndarray]] = []
        shape: dict[str, Any] = {}
        for edges in instrument.routes(instrument.illumination, source, stage):
            lit.append(
                (edges[-1].side, photons * spectrum * _route_transmission(instrument, edges, state, grid))
            )
            if edges[-1].side == "orthogonal":
                lens = instrument.cubes[edges[-1].source].element_at(state)
                shape["sheet"] = _sheet(lens, edges[-1].along, emitter.wavelength)
            if edges[-1].field is not None:
                shape["field_um"] = edges[-1].field * 1000.0
            else:
                shape["spot"] = True
        found[source] = Transfer(
            tuple(lit), through, element.readout.qe, gathered, bands, shape
        )
    return found


#: What a sample sends back of the light landing on it from one side, as a share of it.
Direct = Callable[[str | None], float]
#: What a sample emits, in all directions, for the photons landing on it.
Emits = Callable[[np.ndarray], np.ndarray]


def couple(
    found: Transfer, grid: np.ndarray, direct: Direct, emits: Emits
) -> dict[str, Any]:
    """How many electrons a source makes at the detector, per milliwatt and millisecond, on a
    sample that sends back `direct` of what lands on it and emits what `emits` says.

    That is for a bead, if all of the source's light landed on it: how much does depends on the
    pixel, and `predict.assemble` says. A source on the same side as the detector reaches it by what
    the sample reflects and by what it emits; one on the other side by what it lets through, and
    also by what it emits; a sheet, from across, only by what it emits. Of what is emitted, only
    what the objective gathers goes on; what passes straight through stays in its cone.
    """
    arriving = np.zeros(grid.shape)
    unchanged = np.zeros(grid.shape)  # of that, what the sample only let through or reflected
    for side, on_sample in found.lit:
        back = 0.0 if side == "orthogonal" else direct(side)
        arriving = arriving + on_sample * back + emits(on_sample) * found.gathered
        unchanged = unchanged + on_sample * back
    through = np.zeros(grid.shape)
    for route in found.detection:
        through = through + arriving * route
    through = through * found.qe
    passed = np.zeros(grid.shape)
    for route in found.detection:
        passed = passed + unchanged * route
    total = float(through.sum())
    mean = float((through * grid).sum() / total) if total > 0.0 else None
    result = {
        "electrons_per_mw_ms": total,
        "band_mean_nm": mean,
        "direct_share": float(passed.sum() * found.qe / total) if total > 0.0 else 0.0,
        **found.shape,
    }
    if found.colors:
        result["colors"] = {
            name: float((through * band).sum()) for name, band in found.colors.items()
        }
    return result


def _box(grid: np.ndarray, windows: Iterable[tuple[float, float]]) -> np.ndarray:
    """1 within any of `windows`, 0 elsewhere."""
    inside = np.zeros(grid.shape, dtype=bool)
    for low, high in windows:
        inside |= (grid >= low) & (grid <= high)
    return inside.astype(float)


def reference_coupling(
    found: Transfer, reach: Mapping[str, Any] | None, grid: np.ndarray
) -> dict[str, Any]:
    """`couple` against a stated reference rather than a sample: for a channel of light sent
    straight back (`reach` kind ``direct``), a sample that sends back all of it; for one of light
    emitted, a dye absorbing all of what lands in its excitation windows and emitting it, evenly,
    in its emission windows, and nothing sent back; where no channel is, nothing.

    So what the optics say of a channel does not depend on a simulated sample: how bright a real
    one is, is the sample's.
    """
    if reach is None:
        return couple(found, grid, lambda side: 0.0, lambda on_sample: np.zeros(grid.shape))
    if reach["kind"] == "direct":
        return couple(found, grid, lambda side: 1.0, lambda on_sample: np.zeros(grid.shape))
    excitation = _box(grid, reach["excitation"])
    emission = _box(grid, reach["emission"])
    emission = emission / emission.sum() if emission.sum() > 0.0 else emission

    def emits(on_sample: np.ndarray) -> np.ndarray:
        return (on_sample * excitation).sum() * emission

    return couple(found, grid, lambda side: 0.0, emits)


def _prescription_surfaces(path: str) -> list[dict[str, Any]]:
    """A lens's surfaces as its file states them: never retyped, as one wrong radius is a wrong lens."""
    data = json.loads(Path(path).read_text())
    surfaces = data["surface_group"]["surfaces"][1:-1]  # neither the object nor the image
    found = []
    for surface in surfaces:
        material = surface["material_post"]
        found.append(
            {
                "radius": float(surface["geometry"]["radius"]),
                "z": float(surface["geometry"]["cs"]["z"]),
                "material": material.get("name")
                if material.get("type") != "IdealMaterial"
                else "air",
            }
        )
    return found


def _optic(
    lenses: tuple[tuple[Any, ...], ...],
    object_distance: float,
    na: float,
    index_of: float,
    wavelength_um: float,
    field_mm: float,
) -> Any:  # noqa: ANN401 - optiland has no stub for this
    """A route as optiland takes it: each lens where it is, along the axis and across it."""
    from optiland.materials import IdealMaterial
    from optiland.optic import Optic

    optic = Optic()
    index = 0
    optic.add_surface(
        index=index, radius=np.inf, thickness=object_distance, material=IdealMaterial(index_of)
    )
    for position, lens in enumerate(lenses):
        kind, what, after, x, y, *rest = lens
        if kind == "ideal":
            index += 1
            if position == 0:
                # The stop at the back focal plane: the object side is telecentric, so moving
                # the sample defocuses it and does not change the scale. It is the lens's own, and
                # goes where the lens goes.
                optic.add_surface(
                    index=index, surface_type="paraxial", f=what, thickness=what, dx=x, dy=y
                )
                index += 1
                optic.add_surface(
                    index=index, radius=np.inf, thickness=after - what, is_stop=True, dx=x, dy=y
                )
            else:
                optic.add_surface(
                    index=index, surface_type="paraxial", f=what, thickness=after, dx=x, dy=y
                )
        else:
            (clear_radius,) = rest
            surfaces = _prescription_surfaces(what)
            for i, surface in enumerate(surfaces):
                index += 1
                next_z = surfaces[i + 1]["z"] if i + 1 < len(surfaces) else None
                thickness = next_z - surface["z"] if next_z is not None else after
                optic.add_surface(
                    index=index,
                    radius=surface["radius"],
                    thickness=thickness,
                    material=surface["material"],
                    aperture=2.0 * clear_radius,  # optiland takes the diameter
                    dx=x,
                    dy=y,
                )
    optic.add_surface(index=index + 1)
    optic.set_aperture("objectNA", na)
    optic.fields.set_telecentric(True)
    optic.set_field_type("object_height")
    optic.add_field(y=0.0)
    optic.add_field(y=field_mm)
    optic.add_wavelength(wavelength_um, is_primary=True)
    return optic


def _landing(rays: Any) -> tuple[float, float]:  # noqa: ANN401
    """Where one ray ends, in millimetres."""
    return float(np.ravel(rays.x)[0]), float(np.ravel(rays.y)[0])


@lru_cache(maxsize=512)
def _trace(
    lenses: tuple[tuple[Any, ...], ...],
    sensor: tuple[float, float],
    object_distance: float,
    na: float,
    index: float,
    wavelength_um: float,
    half_diagonal_mm: float,
) -> tuple[float, float, float, float, float, float, float]:
    def build(field_mm: float) -> Any:  # noqa: ANN401 - optiland has no stub for this
        return _optic(lenses, object_distance, na, index, wavelength_um, field_mm)

    def rms(rays: Any) -> tuple[float, float]:  # noqa: ANN401
        x, y = np.asarray(rays.x), np.asarray(rays.y)
        alive = np.isfinite(x) & np.isfinite(y) & (np.asarray(rays.i) > 0)
        if not alive.any():
            return math.nan, 0.0
        spread = (x[alive] - x[alive].mean()) ** 2 + (y[alive] - y[alive].mean()) ** 2
        return float(np.sqrt(spread.mean())) * 1000.0, float(alive.mean())

    # Measured with a ray close to the axis: optiland's paraxial shortcut does not handle a
    # telecentric object side, where the entrance pupil is at infinity. Against where the middle
    # lands: a lens off the axis sends it elsewhere.
    probing = build(1.0)
    middle_x, middle_y = _landing(
        probing.trace_generic(Hx=0, Hy=0, Px=0, Py=0, wavelength=wavelength_um)
    )
    _, probe_y = _landing(
        probing.trace_generic(Hx=0, Hy=0.001, Px=0, Py=0, wavelength=wavelength_um)
    )
    magnification = (probe_y - middle_y) / 0.001
    field = half_diagonal_mm / abs(magnification)
    optic = build(field)
    center_rays = optic.trace(
        Hx=0, Hy=0, wavelength=wavelength_um, num_rays=8, distribution="hexapolar"
    )
    corner_rays = optic.trace(
        Hx=0, Hy=1, wavelength=wavelength_um, num_rays=8, distribution="hexapolar"
    )
    spot_center, alive_center = rms(center_rays)
    spot_corner, alive_corner = rms(corner_rays)
    chief = optic.trace_generic(Hx=0, Hy=1, Px=0, Py=0, wavelength=wavelength_um)
    real_height = _landing(chief)[1] - middle_y
    distortion = (real_height / (magnification * field) - 1.0) * 100.0
    relative = alive_corner / alive_center if alive_center else 0.0
    return (
        magnification,
        distortion,
        relative,
        spot_center,
        spot_corner,
        (middle_x - sensor[0]) * 1000.0,
        (middle_y - sensor[1]) * 1000.0,
    )


#: How far apart the two planes are that say where focus is, in micrometres, and how far out in the
#: pupil the ray that says it: near the axis, so that a lens's aberrations do not move the answer.
_FOCUS_PROBE_UM = 10.0
_FOCUS_PROBE_PUPIL = 0.05


@lru_cache(maxsize=2048)
def _focus_height(
    lenses: tuple[tuple[Any, ...], ...],
    object_distance: float,
    na: float,
    index: float,
    wavelength_um: float,
) -> float:
    """How far from the middle a ray near the axis lands: nothing, where the object is in focus."""
    optic = _optic(lenses, object_distance, na, index, wavelength_um, 1.0)
    _, middle = _landing(optic.trace_generic(Hx=0, Hy=0, Px=0, Py=0, wavelength=wavelength_um))
    _, beside = _landing(
        optic.trace_generic(Hx=0, Hy=0, Px=0, Py=_FOCUS_PROBE_PUPIL, wavelength=wavelength_um)
    )
    return beside - middle


@dataclass(frozen=True)
class _Layout:
    """A route as it stands under some values: each lens and the sensor where its moves put it."""

    lenses: tuple[tuple[Any, ...], ...]  # as `_optic` takes them
    sensor: tuple[float, float]  # across the axis, in millimetres
    to_first: float  # from where the sample starts to the first lens, in millimetres
    first_moved_um: float  # how far of that the lens has moved, along the axis
    na: float
    index: float
    reflections: int

    def in_focus_um(self, wavelength_um: float) -> float:
        """Where the plane in focus is, from where the sample starts, away from the lens."""
        heights = [
            _focus_height(
                self.lenses, self.to_first + plane / 1000.0, self.na, self.index, wavelength_um
            )
            for plane in (0.0, _FOCUS_PROBE_UM)
        ]
        if heights[1] == heights[0]:
            return 0.0
        return -heights[0] * _FOCUS_PROBE_UM / (heights[1] - heights[0])


def _layout(
    instrument: Instrument,
    detector: str,
    state: Mapping[str, Any],
    errors: Errors,
) -> _Layout:
    """Place everything on the one route from the sample to `detector`, as `state` has it.

    Along the axis, a cube is where the distances put it, and its moves along the axis from there;
    across it, where its moves along x and y put it. Only where a lens and the sensor are changes
    what is seen: a flat filter, moved, is the same filter.
    """
    stage = instrument.seen_sample(detector, state)
    routes = instrument.detection_routes(detector, state)
    if len(routes) != 1:
        raise ValueError(f"{detector}: {len(routes)} routes from the sample; one is handled")
    route = routes[0]

    def moved(name: str, along: str) -> float:
        """How far `name` has moved along `along`, in millimetres."""
        return sum(
            state[v.name] / 1000.0
            for v in instrument.cubes[name].variables.values()
            if v.verb == "moves" and v.along == along
        )

    placed: list[tuple[str, Any, float]] = []  # each lens: its cube, its element, where it is
    at = 0.0
    for edge in route:
        target = instrument.cubes[edge.target].element_at(state)
        distance = edge.distance if edge.distance not in (None, "focus") else 0.0
        if edge.distance == "focus":
            # the lens this distance belongs to, as really built
            lens = (
                target if target.kind == "lens" else instrument.cubes[edge.source].element_at(state)
            )
            focal = lens.f
            if not placed or (len(placed) == 1 and lens is placed[0][1]):
                focal *= errors.objective_focal_factor
            # In a medium, what is in focus is that much further from the lens.
            distance = focal * (lens.index if edge.source == stage else 1.0)
        at += float(distance)
        if target.kind == "lens":
            placed.append((edge.target, target, at + moved(edge.target, "axis")))
    if not placed:
        raise ValueError(f"{detector}: no lens on the way from the sample")
    ends = [*(where for _, _, where in placed[1:]), at + moved(detector, "axis")]
    lenses = []
    for position, ((name, lens, where), end) in enumerate(zip(placed, ends)):
        across = (moved(name, "x"), moved(name, "y"))
        if lens.prescription is not None:
            lenses.append(
                (
                    "prescription",
                    str(instrument.folder / lens.prescription),
                    end - where,
                    *across,
                    lens.clear_radius,
                )
            )
        else:
            focal = lens.f * (errors.objective_focal_factor if position == 0 else 1.0)
            lenses.append(("ideal", focal, end - where, *across))
    first_name, first, to_first = placed[0]
    return _Layout(
        lenses=tuple(lenses),
        sensor=(moved(detector, "x"), moved(detector, "y")),
        to_first=to_first,
        first_moved_um=moved(first_name, "axis") * 1000.0,
        na=first.na,
        index=first.index,
        reflections=sum(1 for edge in route if edge.via == "reflect"),
    )


def _as_it_starts(instrument: Instrument, state: Mapping[str, Any]) -> dict[str, Any]:
    """`state`, with everything that moves back where it starts."""
    return {
        **state,
        **{v.name: v.initial for v in instrument.variables.values() if v.verb == "moves"},
    }


def _scan_sample(instrument: Instrument, scanner: str) -> str:
    """The sample a scanner walks the light over."""
    return next(
        sample
        for sample in instrument.samples()
        if instrument.routes(instrument.illumination, scanner, sample)
    )


def _scan_route(instrument: Instrument, scanner: str) -> tuple[Edge, ...]:
    return instrument.routes(instrument.illumination, scanner, _scan_sample(instrument, scanner))[0]


def scan_um_per_degree(
    instrument: Instrument, scanner: str, state: Mapping[str, Any], errors: Errors = Errors()
) -> float:
    """How far the spot moves on the sample per degree of `scanner`, by a ray through thin lenses.

    Signed like a magnification: a relay inverts.
    """
    route = _scan_route(instrument, scanner)
    elements = [instrument.cubes[edge.target].element_at(state) for edge in route]
    lenses = [index for index, element in enumerate(elements) if element.kind == "lens"]
    height, angle = 0.0, 1.0  # in millimetres, and per radian
    for index, edge in enumerate(route):
        if edge.distance == "focus":
            # the lens this distance belongs to, as the detection path reads it
            lens = elements[index] if index in lenses else elements[index - 1]
            distance = lens.f * (
                errors.objective_focal_factor if lens is elements[lenses[-1]] else 1.0
            )
        else:
            distance = edge.distance
        height += distance * angle
        if index in lenses:
            focal = elements[index].f
            if index == lenses[-1]:
                focal *= errors.objective_focal_factor
            angle -= height / focal
    return height * 1000.0 * math.pi / 180.0


def _scan_imaging(
    instrument: Instrument,
    scanner: str,
    state: Mapping[str, Any],
    errors: Errors,
    defocused_um: float | None = None,
) -> Imaging:
    """A scan as a sensor measured in angle: a step for a pitch, degrees for micrometres.

    So ``pitch / magnification`` is still micrometres per pixel, and an Airy disc in the same terms
    still comes out in pixels.
    """
    route = _scan_route(instrument, scanner)
    last = [
        element
        for edge in route
        if (element := instrument.cubes[edge.target].element_at(state)).kind == "lens"
    ][-1]
    um_per_degree = scan_um_per_degree(instrument, scanner, state, errors)
    magnification = 1.0 / um_per_degree
    nearest = next(
        edge.target for edge in route if instrument.cubes[edge.target].element_at(state) is last
    )
    # Whichever moves: the sample, or the lens nearest it.
    lens_um = sum(
        state[variable.name]
        for variable in instrument.cubes[nearest].variables.values()
        if variable.verb == "moves" and variable.along == "axis"
    )
    sample = _scan_sample(instrument, scanner)
    defocus_um = (
        instrument.lit_um(state, lens_um, sample=sample) + lens_um
        if defocused_um is None
        else defocused_um
    )
    return Imaging(
        magnification=magnification,
        reflections=sum(1 for edge in route if edge.via == "reflect"),
        distortion_percent=0.0,
        relative_illumination=1.0,
        spot_center_um=abs(defocus_um) * last.na / last.index * abs(magnification),
        spot_corner_um=abs(defocus_um) * last.na / last.index * abs(magnification),
        numerical_aperture=last.na / abs(magnification),
        focus_um=lens_um,
    )


def imaging(
    instrument: Instrument,
    detector: str,
    state: Mapping[str, Any],
    wavelength_nm: float,
    errors: Errors = Errors(),
    defocused_um: float | None = None,
) -> Imaging:
    """Trace the route from the sample to `detector` under `state`.

    How far what is seen is from focus follows from `state`, or is `defocused_um`.
    """
    scanner = instrument.scanner_of(detector)
    if scanner is not None:
        return _scan_imaging(instrument, scanner, state, errors, defocused_um)
    stage = instrument.seen_sample(detector, state)
    wavelength_um = wavelength_nm / 1000.0
    layout = _layout(instrument, detector, state, errors)
    # Where focus is, counted from where the description puts it: as it starts, a microscope is in
    # focus where its distances say, and what has moved since moves it from there. A lens nearest
    # the sample takes it along one for one; anything else, as far as tracing finds.
    start = _layout(instrument, detector, _as_it_starts(instrument, state), errors)
    focus_um = layout.first_moved_um
    if (layout.lenses, layout.to_first) != (start.lenses, start.to_first):
        focus_um = (
            start.first_moved_um
            + start.in_focus_um(wavelength_um)
            - layout.in_focus_um(wavelength_um)
        )
    if defocused_um is None:
        object_distance = (
            layout.to_first + instrument.lit_um(state, focus_um, sample=stage) / 1000.0
        )
    else:
        object_distance = layout.to_first - layout.first_moved_um / 1000.0 + defocused_um / 1000.0

    axes = instrument.cubes[detector].element_at(state).axes
    half_diagonal = math.hypot(
        axes["x"].size * axes["x"].pitch / 2000.0,
        axes["y"].size * axes["y"].pitch / 2000.0,
    )
    magnification, distortion, relative, spot_center, spot_corner, shift_x, shift_y = _trace(
        layout.lenses,
        layout.sensor,
        object_distance,
        layout.na,
        layout.index,
        wavelength_um,
        half_diagonal,
    )
    return Imaging(
        magnification=magnification,
        reflections=layout.reflections,
        distortion_percent=distortion,
        relative_illumination=relative,
        spot_center_um=spot_center,
        spot_corner_um=spot_corner,
        numerical_aperture=layout.na / abs(magnification),
        shift_x_um=shift_x,
        shift_y_um=shift_y,
        focus_um=focus_um,
    )
