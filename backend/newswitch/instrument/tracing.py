"""What light does on its way: ray tracing for geometry, and transmission curves for colour.

The only module that imports optiland, and only when it traces, because this runs at compile time
on a real computer: a microscope only ever reads what came out (`newswitch.instrument.predict`).

Each route is traced on its own, as a straight line with mirrors unfolded: optiland traces one
sequence of surfaces, and branching is the job of the routes. Filters and dichroics only shape the
spectrum here, as they are thin and flat, and a mirror only flips the image.

Errors can be passed in (`Errors`), so the same tracer can describe a microscope that is not quite
what its description says. Nominal predictions pass none.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from newswitch.instrument.spec import Edge, Element, Instrument

#: The spectrum everything is computed on, in nanometres.
WAVELENGTHS = np.arange(350.0, 801.0, 1.0)


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


def _gaussian(center: float, width: float) -> np.ndarray:
    return np.exp(-0.5 * ((WAVELENGTHS - center) / (width / 2.355)) ** 2)


def transmission(element: Element, via: str | None) -> np.ndarray:
    """How much of each wavelength an element lets through, leaving the way `via` says."""
    properties = element.properties
    if element.kind == "dichroic":
        passes = 1.0 / (1.0 + np.exp(-(WAVELENGTHS - properties["cut"]) / 2.0))
        return passes if via == "transmit" else 1.0 - passes
    if element.kind == "splitter":
        return np.full(WAVELENGTHS.shape, float(properties[via or "transmit"]))
    if element.kind == "filter" and "center" in properties:
        half = properties["width"] / 2.0
        edge = (np.abs(WAVELENGTHS - properties["center"]) - half) / 2.0
        return 0.95 / (1.0 + np.exp(edge))
    return np.ones(WAVELENGTHS.shape)


def _route_transmission(
    instrument: Instrument, route: tuple[Edge, ...], state: Mapping[str, Any]
) -> np.ndarray:
    curve = np.ones(WAVELENGTHS.shape)
    for edge in route:
        curve = curve * transmission(instrument.cubes[edge.source].element_at(state), edge.via)
    return curve


def coupling(
    instrument: Instrument, detector: str, state: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """How much of each source reaches `detector` through the sample, per milliwatt.

    A source on the same side as the detector reaches it by what the sample reflects and by what
    it emits; one on the other side by what it lets through, and also by what it emits.
    """
    sample = instrument.sample
    stage = instrument.sample_cube()
    detection = instrument.routes(instrument.detection, stage, detector)
    excitation = _gaussian(sample["excitation"], sample["excitation_width"])
    emission = _gaussian(sample["emission"], sample["emission_width"])
    emission = emission / emission.sum()
    result: dict[str, dict[str, Any]] = {}
    for source in instrument.sources():
        element = instrument.cubes[source].element_at(state)
        spectrum = _gaussian(element.properties["wavelength"], element.properties["width"])
        spectrum = spectrum / spectrum.sum()
        arriving = np.zeros(WAVELENGTHS.shape)
        for edges in instrument.routes(instrument.illumination, source, stage):
            on_sample = spectrum * _route_transmission(instrument, edges, state)
            direct = sample["reflect"] if edges[-1].side == "epi" else sample["transmit"]
            emitted = (on_sample * excitation).sum() * sample["quantum_yield"] * emission
            arriving = arriving + on_sample * direct + emitted
        through = np.zeros(WAVELENGTHS.shape)
        for edges in detection:
            through = through + arriving * _route_transmission(instrument, edges, state)
        total = float(through.sum())
        mean = float((through * WAVELENGTHS).sum() / total) if total > 1e-12 else None
        result[source] = {"light_per_mw": total, "band_mean_nm": mean}
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
    wavelength_um: float,
    half_diagonal_mm: float,
) -> tuple[float, float, float, float, float]:
    from optiland.optic import Optic

    def build(field_mm: float) -> Any:  # noqa: ANN401 - optiland has no stub for this
        optic = Optic()
        index = 0
        optic.add_surface(index=index, radius=np.inf, thickness=object_distance)
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


def imaging(
    instrument: Instrument,
    detector: str,
    state: Mapping[str, Any],
    wavelength_nm: float,
    errors: Errors = Errors(),
) -> Imaging:
    """Trace the route from the sample to `detector` under `state`."""
    stage = instrument.sample_cube()
    routes = instrument.routes(instrument.detection, stage, detector)
    if len(routes) != 1:
        raise ValueError(f"{detector}: {len(routes)} routes from the sample; one is handled")
    route = routes[0]
    lenses: list[tuple[Any, ...]] = []
    object_distance = 0.0
    reflections = sum(1 for edge in route if edge.via == "reflect")
    objective_f: float | None = None
    na: float | None = None
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
            focal = lens.properties["f"]
            if not lenses:
                focal *= errors.objective_focal_factor
            distance = focal
        distance_since_lens += float(distance)
        if target.kind == "lens":
            if not lenses and object_distance == 0.0 and pending is None:
                object_distance = distance_since_lens + moved(stage)
            elif pending is not None:
                lenses.append(_lens(pending, distance_since_lens + moved(edge.target)))
            if "prescription" in target.properties:
                pending = {
                    "kind": "prescription",
                    "what": str(instrument.folder / target.properties["prescription"]),
                    "clear_radius": target.properties.get("clear_radius", 11.43),
                }
            else:
                focal = target.properties["f"]
                if objective_f is None:
                    focal *= errors.objective_focal_factor
                    objective_f = focal
                    na = target.properties["na"]
                pending = {"kind": "ideal", "what": focal}
            distance_since_lens = -moved(edge.target) if pending["kind"] == "prescription" else 0.0
    assert pending is not None and na is not None
    lenses.append(_lens(pending, distance_since_lens))

    axes = instrument.cubes[detector].element_at(state).properties["axes"]
    half_diagonal = math.hypot(
        axes["x"]["size"] * axes["x"]["pitch"] / 2000.0,
        axes["y"]["size"] * axes["y"]["pitch"] / 2000.0,
    )
    magnification, distortion, relative, spot_center, spot_corner = _trace(
        tuple(lenses), object_distance, na, wavelength_nm / 1000.0, half_diagonal
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
