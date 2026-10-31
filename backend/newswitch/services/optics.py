"""What the optics find under the current values, and the light paths the description states.

Nothing here decides what a microscope is made of. Which cubes are on the way, what is in place in
them and what they are set to all come from the instrument; what they do comes from tracing it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Any

import numpy as np

from newswitch.instrument import spec, tracing
from newswitch.instrument.compiler import compile_instrument, influences
from newswitch.instrument.predict import Answer, state_key
from newswitch.instrument.spec import Instrument
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.light_path import LightEdge, LightElement, LightPath, LightPathSnapshot
from newswitch.models.optics import DetectorOptics, OpticalChannel, SourceOptics
from newswitch.states.calibration import CalibrationState
from newswitch.states.detector import CameraState
from newswitch.states.optics import OpticsState


def _digest(payload: Mapping[str, Any]) -> str:
    """A stable hash of `payload`, whatever the order of its keys."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.blake2b(encoded, digest_size=16).hexdigest()


def _facts(element: spec.Element) -> dict[str, str]:
    """What an element is made of, as it should read."""
    facts: dict[str, str] = {}
    match element:
        case spec.Source():
            facts["emits"] = element.emits
            facts["wavelength"] = ", ".join(f"{line.center:g} nm" for line in element.spectrum)
            facts["max power"] = f"{element.max_power:g} mW"
        case spec.Lens():
            if element.f is not None:
                facts["focal length"] = f"{element.f:g} mm"
            if element.na is not None:
                facts["NA"] = f"{element.na:g}"
                facts["immersion"] = f"n = {element.index:g}"
            if element.magnification is not None:
                facts["magnification"] = f"{element.magnification:g}x"
            if element.prescription is not None:
                facts["prescription"] = element.prescription
        case spec.Filter(curve=curve) | spec.Dichroic(curve=curve):
            facts["curve"] = "open" if curve is None else curve.type
            for name in ("center", "width", "cut"):
                if hasattr(curve, name):
                    facts[name] = f"{getattr(curve, name):g} nm"
            if hasattr(curve, "peak"):
                facts["peak"] = f"{curve.peak:.0%}"
        case spec.Splitter():
            facts["reflects"] = f"{element.reflect:.0%}"
            facts["transmits"] = f"{element.transmit:.0%}"
        case spec.Sensor():
            facts["pixels"] = f"{element.axes['x'].size} x {element.axes['y'].size}"
            facts["pitch"] = f"{element.axes['x'].pitch:g} um"
            facts["bit depth"] = str(element.readout.bit_depth)
        case spec.PointDetector():
            facts["bit depth"] = str(element.readout.bit_depth)
            for name, axis in element.axes.items():
                facts[name] = f"{axis.size} x {axis.step:g} ps"
        case spec.Scanner():
            facts["steps"] = f"{element.axes['x'].size} x {element.axes['y'].size}"
            facts["per step"] = f"{element.axes['x'].step:g} deg"
        case spec.Pinhole():
            facts["diameter"] = f"{element.diameter:g} um"
    return facts


def _reading(variable: spec.Variable, value: Any) -> str:  # noqa: ANN401 - a variable's value
    """A variable's value, as it should read."""
    if variable.verb == "swaps":
        element = variable.slots[value]
        return getattr(element, "name", None) or f"slot {value}"
    return f"{value:g} {variable.unit}".strip()


class OpticsManager:
    """Publishes what the optics find, and says where a detector's pixels are."""

    def __init__(
        self,
        state: OpticsState,
        camera_state: CameraState,
        calibration_state: CalibrationState,
        instrument: Instrument | None = None,
        values: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        """A manager of `instrument`'s optics, whose current values `values` gives."""
        self.state = state
        self.camera_state = camera_state
        self.calibration_state = calibration_state
        self.instrument = instrument
        self.values = values or dict
        self.table = None if instrument is None else compile_instrument(instrument)
        self._influences: dict[str, frozenset[str]] | None = None
        self._published: dict[str, str] = {}

    def _name(self, detector_slot: int) -> str:
        assert self.instrument is not None
        return self.instrument.detectors()[detector_slot - 1]

    def _path(self, name: str, values: Mapping[str, Any]) -> LightPath:
        """Every way light can take to the detector `name`, as the edges say."""
        assert self.instrument is not None
        edges = self.instrument.edges_to(name)
        cubes = dict.fromkeys(cube for edge in edges for cube in (edge.source, edge.target))
        return LightPath(
            detector=name,
            elements=[self._element(cube, values) for cube in cubes or [name]],
            edges=[LightEdge(e.source, e.target, e.via, e.side) for e in edges],
        )

    def _element(self, name: str, values: Mapping[str, Any]) -> LightElement:
        assert self.instrument is not None
        cube = self.instrument.cubes[name]
        element = cube.element_at(values)
        return LightElement(
            name=name,
            kind=element.kind,
            label=getattr(element, "name", None) or name,
            facts=_facts(element),
            values={
                variable.name: _reading(variable, values[variable.name])
                for variable in cube.variables.values()
            },
        )

    def get_light_path_for_detector(self, detector_slot: int) -> LightPath:
        """The light path of the detector in a slot, as things are now."""
        return self._path(self._name(detector_slot), self.values())

    def snapshot(self, path: LightPath) -> LightPathSnapshot:
        """`path` as things are now, keyed by what a calibration of it depends on."""
        assert self.instrument is not None
        if self._influences is None:
            self._influences = influences(self.instrument)
        values = self.values()
        slot = self.instrument.detectors().index(path.detector) + 1
        key = _digest(
            {
                "detector": path.detector,
                "region": self.camera_state.get_detector_for_slot(slot).current_roi,
                **{variable: values[variable] for variable in self._influences[path.detector]},
            }
        )
        return LightPathSnapshot(
            key=key,
            hash=_digest(
                {
                    "key": key,
                    **{
                        variable.name: values[variable.name]
                        for variable in self.instrument.variables.values()
                        if variable.verb == "swaps" or variable.cube in self.instrument.sources()
                    },
                }
            ),
            elements=path.elements,
            edges=path.edges,
        )

    def predicted(self, detector_slot: int) -> CalibratedLightPath:
        """What the optics predict for a detector, in the terms of a calibration of it."""
        assert self.table is not None
        answer = self.table.answer(self._name(detector_slot), self.values())
        (xx, xy), (yx, yy) = answer.pixel_to_stage
        return CalibratedLightPath(
            # A calibration says how far the stage moves to shift the image by a pixel: the
            # opposite of the sample point that pixel sees.
            affine_matrix=[
                [-xx, -xy, 0.0, 0.0],
                [-yx, -yy, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            fov_width=answer.field_of_view_um[0],
            fov_height=answer.field_of_view_um[1],
        )

    def depth_of_field_um(self, detector_slot: int) -> float:
        """How deep what the detector in a slot sees sharply is, from its objective's NA."""
        assert self.instrument is not None
        return tracing.depth_of_field_um(self.instrument, self._name(detector_slot), self.values())

    def _detector(self, slot: int, name: str, values: Mapping[str, Any]) -> DetectorOptics:
        assert self.table is not None and self.instrument is not None
        answer: Answer = self.table.answer(name, values)
        path = self._path(name, values)
        snapshot = self.snapshot(path)
        try:
            found = self.calibration_state.get_calibrated_path(snapshot)
            calibrated = True
        except ValueError:
            found = self.predicted(slot)
            calibrated = False
        matrix = found.affine_matrix
        return DetectorOptics(
            name=name,
            calibrated=calibrated,
            pixel_to_stage=[[-matrix[0][0], -matrix[0][1]], [-matrix[1][0], -matrix[1][1]]],
            pixel_um=float(np.hypot(matrix[0][0], matrix[1][0])),
            field_width_um=abs(found.fov_width),
            field_height_um=abs(found.fov_height),
            spot_px=answer.spot_px,
            expected_counts=answer.light,
            read_noise_counts=answer.read_noise_counts,
            band_nm=answer.band_nm,
            depth_of_field_um=tracing.depth_of_field_um(self.instrument, name, values),
            path=path,
        )

    def _source(self, name: str, values: Mapping[str, Any]) -> SourceOptics:
        assert self.table is not None and self.instrument is not None
        sample = self.instrument.sample_cube()
        sides = [
            route[-1].side
            for route in self.instrument.routes(self.instrument.illumination, name, sample)
        ]
        side = sides[0] if sides else None
        entries = self.table.states[state_key(self.instrument, values)]
        arriving = next(
            (entry["coupling"][name] for entry in entries.values() if name in entry["coupling"]),
            {},
        )
        sheet = arriving.get("sheet")
        if sheet is not None:
            return SourceOptics(
                name=name,
                shape="sheet",
                side=side,
                field_um=arriving.get("field_um"),
                thickness_um=2.0 * sheet["waist_um"],
                reach_um=sheet["rayleigh_um"],
                along=sheet["along"],
            )
        if "field_um" in arriving:
            return SourceOptics(name=name, shape="field", side=side, field_um=arriving["field_um"])
        return SourceOptics(name=name, shape="spot", side=side)

    def _publish(self, field: str, value: Any) -> None:  # noqa: ANN401 - any of the state's fields
        """Set a field of the state, if it changed: what clients hold stays what they hold.

        Compared as text: a published value is turned into another class, so never equals a new one.
        """
        text = json.dumps(value, sort_keys=True, default=asdict)
        if self._published.get(field) != text:
            self._published[field] = text
            setattr(self.state, field, value)

    def refresh(self) -> None:
        """Publish what the optics find under the current values, as far as that changed."""
        if self.instrument is None or self.table is None:
            return
        values = self.values()
        self._publish(
            "detectors",
            {
                name: self._detector(slot, name, values)
                for slot, name in enumerate(self.instrument.detectors(), start=1)
                if any(d.slot == slot for d in self.camera_state.detectors)
            },
        )
        self._publish(
            "sources", {name: self._source(name, values) for name in self.instrument.sources()}
        )
        self._publish(
            "channels",
            [
                OpticalChannel(c.source, c.detector, c.electrons, c.band_nm)
                for c in self.table.channels(values)
            ],
        )
