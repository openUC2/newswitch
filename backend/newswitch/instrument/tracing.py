"""What light does on its way: ray tracing for geometry, and transmission curves for colour.

The only module that imports optiland, and only when it traces: a scan needs no ray tracing, so an
instrument with nothing else never loads it. A server traces when it starts (`compiler`).

Each route is traced on its own, as a straight line with mirrors unfolded: optiland traces one
sequence of surfaces, and branching is the job of the routes. Filters and dichroics only shape the
spectrum here, as they are thin and flat, and a mirror only flips the image.

Errors can be passed in (`Errors`), so the same tracer can describe a microscope that is not quite
what its description says. Nominal predictions pass none.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Mapping
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
    Fluorophore,
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


def wavelengths(instrument: Instrument) -> np.ndarray:
    """The spectrum everything of `instrument` is computed on, in nanometres."""
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
    for simulation in (
        simulation
        for sample in instrument.samples()
        for simulation in instrument.sample_holder(sample).simulations.values()
    ):
        if simulation.fluorophore is not None:
            stated += [simulation.fluorophore.excitation, simulation.fluorophore.emission]
    low = max(math.floor(min(stated, default=550.0) - _MARGIN), 1)
    high = math.ceil(max(stated, default=550.0) + _MARGIN)
    return np.arange(float(low), float(high) + 1.0, 1.0)


def _gaussian(grid: np.ndarray, center: float, width: float) -> np.ndarray:
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


def _emitted(
    fluorophore: Fluorophore | None, absorbed: float | None, on_sample: np.ndarray, grid: np.ndarray
) -> np.ndarray:
    """How many photons a bead emits, in all directions, for the photons on it."""
    if fluorophore is None or absorbed is None:
        return np.zeros(grid.shape)
    excitation = _gaussian(grid, fluorophore.excitation, fluorophore.excitation_width)
    emission = _gaussian(grid, fluorophore.emission, fluorophore.emission_width)
    emission = emission / emission.sum()
    return (on_sample * excitation).sum() * absorbed * fluorophore.quantum_yield * emission


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


def coupling(
    instrument: Instrument, detector: str, state: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """How many electrons each source makes at `detector`, per milliwatt and millisecond.

    That is for a bead, if all of the source's light landed on it: how much does depends on the
    pixel, and `predict.assemble` says. A source on the same side as the detector reaches it by what
    the sample reflects and by what it emits; one on the other side by what it lets through, and
    also by what it emits; a sheet, from across, only by what it emits. Of what is emitted, only
    what the objective gathers goes on; what passes straight through stays in its cone.
    """
    grid = wavelengths(instrument)
    stage = instrument.seen_sample(detector, state)
    sample = instrument.simulation_at(state, stage)
    detection = instrument.detection_routes(detector, state)
    element = instrument.cubes[detector].element_at(state)
    colors = element.colors if isinstance(element, Sensor) else {}
    gathered = collected(_objective(instrument, detection, state))
    result: dict[str, dict[str, Any]] = {}
    for source in instrument.sources():
        emitter = instrument.cubes[source].element_at(state)
        spectrum = np.sum(
            [_gaussian(grid, line.center, line.width) for line in emitter.spectrum], axis=0
        )
        spectrum = spectrum / spectrum.sum()
        # photons per milliwatt and millisecond: a microjoule's worth, at its wavelength
        photons = 1e-6 * emitter.wavelength * 1e-9 / _HC
        arriving = np.zeros(grid.shape)
        unchanged = np.zeros(grid.shape)  # of that, what the sample only let through or reflected
        shape: dict[str, Any] = {}
        for edges in instrument.routes(instrument.illumination, source, stage):
            on_sample = photons * spectrum * _route_transmission(instrument, edges, state, grid)
            side = edges[-1].side
            direct = (
                0.0
                if side == "orthogonal"
                else (sample.reflect if side == "epi" else sample.transmit)
            )
            emitted = _emitted(sample.fluorophore, sample.absorbed, on_sample, grid)
            arriving = arriving + on_sample * direct + emitted * gathered
            unchanged = unchanged + on_sample * direct
            if side == "orthogonal":
                lens = instrument.cubes[edges[-1].source].element_at(state)
                shape["sheet"] = _sheet(lens, edges[-1].along, emitter.wavelength)
            if edges[-1].field is not None:
                shape["field_um"] = edges[-1].field * 1000.0
            else:
                shape["spot"] = True
        through = np.zeros(grid.shape)
        for edges in detection:
            through = through + arriving * _route_transmission(instrument, edges, state, grid)
        through = through * element.readout.qe
        passed = np.zeros(grid.shape)
        for edges in detection:
            passed = passed + unchanged * _route_transmission(instrument, edges, state, grid)
        total = float(through.sum())
        mean = float((through * grid).sum() / total) if total > 0.0 else None
        result[source] = {
            "electrons_per_mw_ms": total,
            "band_mean_nm": mean,
            "direct_share": float(passed.sum() * element.readout.qe / total)
            if total > 0.0
            else 0.0,
            **shape,
        }
        if colors:
            result[source]["colors"] = {
                name: float((through * _gaussian(grid, color.center, color.width)).sum())
                for name, color in colors.items()
            }
    return result


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


@lru_cache(maxsize=512)
def _trace(
    lenses: tuple[tuple[Any, ...], ...],
    object_distance: float,
    na: float,
    index: float,
    wavelength_um: float,
    half_diagonal_mm: float,
) -> tuple[float, float, float, float, float]:
    from optiland.materials import IdealMaterial
    from optiland.optic import Optic

    index_of = index

    def build(field_mm: float) -> Any:  # noqa: ANN401 - optiland has no stub for this
        optic = Optic()
        index = 0
        optic.add_surface(
            index=index, radius=np.inf, thickness=object_distance, material=IdealMaterial(index_of)
        )
        for position, lens in enumerate(lenses):
            kind, *rest = lens
            if kind == "ideal":
                f, after = rest
                index += 1
                if position == 0:
                    # The stop at the back focal plane: the object side is telecentric, so moving
                    # the sample defocuses it and does not change the scale.
                    optic.add_surface(index=index, surface_type="paraxial", f=f, thickness=f)
                    index += 1
                    optic.add_surface(index=index, radius=np.inf, thickness=after - f, is_stop=True)
                else:
                    optic.add_surface(index=index, surface_type="paraxial", f=f, thickness=after)
            else:
                path, after, clear_radius = rest
                surfaces = _prescription_surfaces(path)
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
                    )
        optic.add_surface(index=index + 1)
        optic.set_aperture("objectNA", na)
        optic.fields.set_telecentric(True)
        optic.set_field_type("object_height")
        optic.add_field(y=0.0)
        optic.add_field(y=field_mm)
        optic.add_wavelength(wavelength_um, is_primary=True)
        return optic

    def rms(rays: Any) -> tuple[float, float]:  # noqa: ANN401
        x, y = np.asarray(rays.x), np.asarray(rays.y)
        alive = np.isfinite(x) & np.isfinite(y) & (np.asarray(rays.i) > 0)
        if not alive.any():
            return math.nan, 0.0
        spread = (x[alive] - x[alive].mean()) ** 2 + (y[alive] - y[alive].mean()) ** 2
        return float(np.sqrt(spread.mean())) * 1000.0, float(alive.mean())

    # Measured with a ray close to the axis: optiland's paraxial shortcut does not handle a
    # telecentric object side, where the entrance pupil is at infinity.
    probe = build(1.0).trace_generic(Hx=0, Hy=0.001, Px=0, Py=0, wavelength=wavelength_um)
    magnification = float(np.ravel(probe.y)[0]) / 0.001
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
    real_height = float(np.ravel(chief.y)[0])
    distortion = (real_height / (magnification * field) - 1.0) * 100.0
    relative = alive_corner / alive_center if alive_center else 0.0
    return magnification, distortion, relative, spot_center, spot_corner


def _lens(pending: Mapping[str, Any], after: float) -> tuple[Any, ...]:
    if pending["kind"] == "prescription":
        return ("prescription", pending["what"], after, pending["clear_radius"])
    return ("ideal", pending["what"], after)


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


def focus_moves(instrument: Instrument, detector: str, state: Mapping[str, Any]) -> list[str]:
    """What moves a detector's focus: the sample, and the lens nearest it, along the axis."""
    scanner = instrument.scanner_of(detector)
    if scanner is not None:
        route = _scan_route(instrument, scanner)
        last = [
            element
            for edge in route
            if (element := instrument.cubes[edge.target].element_at(state)).kind == "lens"
        ][-1]
        nearest = next(
            edge.target for edge in route if instrument.cubes[edge.target].element_at(state) is last
        )
    else:
        route = instrument.detection_routes(detector, state)[0]
        nearest = next(
            edge.target
            for edge in route
            if instrument.cubes[edge.target].element_at(state).kind == "lens"
        )
    return [
        *(move.name for move in instrument.sample_moves(instrument.seen_sample(detector, state))),
        *(
            variable.name
            for variable in instrument.cubes[nearest].variables.values()
            if variable.verb == "moves" and variable.along == "axis"
        ),
    ]


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
    routes = instrument.detection_routes(detector, state)
    if len(routes) != 1:
        raise ValueError(f"{detector}: {len(routes)} routes from the sample; one is handled")
    route = routes[0]
    lenses: list[tuple[Any, ...]] = []
    object_distance = 0.0
    reflections = sum(1 for edge in route if edge.via == "reflect")
    objective_f: float | None = None
    na: float | None = None
    immersion: float | None = None
    distance_since_lens = 0.0
    pending: dict[str, Any] | None = None

    def moved(name: str) -> float:
        """How far `name` has moved along the axis, in millimetres."""
        cube = instrument.cubes[name]
        return sum(
            state[v.name] / 1000.0
            for v in cube.variables.values()
            if v.verb == "moves" and v.along == "axis"
        )

    for position, edge in enumerate(route):
        target = instrument.cubes[edge.target].element_at(state)
        distance = edge.distance if edge.distance not in (None, "focus") else 0.0
        if edge.distance == "focus":
            # the lens this distance belongs to, as really built
            lens = (
                target if target.kind == "lens" else instrument.cubes[edge.source].element_at(state)
            )
            focal = lens.f
            if not lenses:
                focal *= errors.objective_focal_factor
            # In a medium, what is in focus is that much further from the lens.
            distance = focal * (lens.index if edge.source == stage else 1.0)
        distance_since_lens += float(distance)
        if target.kind == "lens":
            if not lenses and object_distance == 0.0 and pending is None:
                # Whichever moves: the sample, or the lens nearest it.
                lens_um = moved(edge.target) * 1000.0
                defocus_um = (
                    instrument.lit_um(state, lens_um, sample=stage) + lens_um
                    if defocused_um is None
                    else defocused_um
                )
                object_distance = distance_since_lens + defocus_um / 1000.0
            elif pending is not None:
                lenses.append(_lens(pending, distance_since_lens + moved(edge.target)))
            if target.prescription is not None:
                if not lenses and pending is None:
                    na, immersion = target.na, target.index
                pending = {
                    "kind": "prescription",
                    "what": str(instrument.folder / target.prescription),
                    "clear_radius": target.clear_radius,
                }
            else:
                focal = target.f
                if objective_f is None:
                    focal *= errors.objective_focal_factor
                    objective_f = focal
                    na = target.na
                    immersion = target.index
                pending = {"kind": "ideal", "what": focal}
            distance_since_lens = -moved(edge.target) if pending["kind"] == "prescription" else 0.0
    assert pending is not None and na is not None and immersion is not None
    lenses.append(_lens(pending, distance_since_lens))

    axes = instrument.cubes[detector].element_at(state).axes
    half_diagonal = math.hypot(
        axes["x"].size * axes["x"].pitch / 2000.0,
        axes["y"].size * axes["y"].pitch / 2000.0,
    )
    magnification, distortion, relative, spot_center, spot_corner = _trace(
        tuple(lenses), object_distance, na, immersion, wavelength_nm / 1000.0, half_diagonal
    )
    return Imaging(
        magnification=magnification,
        reflections=reflections,
        distortion_percent=distortion,
        relative_illumination=relative,
        spot_center_um=spot_center,
        spot_corner_um=spot_corner,
        numerical_aperture=na / abs(magnification),
    )
