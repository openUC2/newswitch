"""What the optics find under the current values, and the light paths the description states.

Nothing here decides what a microscope is made of. Which cubes are on the way, what is in place in
them and what they are set to all come from the instrument; what they do comes from tracing it.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Any

import numpy as np

from newswitch.instrument import spec, tracing
from newswitch.instrument.compiler import compile_instrument, influences
from newswitch.instrument.predict import Answer, state_key
from newswitch.instrument.roles import Roles
from newswitch.instrument.spec import Instrument
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.light_path import LightEdge, LightElement, LightPath, LightPathSnapshot
from newswitch.services.element_facts import facts_of, spectrum_color
from newswitch.models.optics import ChannelSwap, DetectorOptics, OpticalChannel, SourceOptics
from newswitch.states.calibration import CalibrationState
from newswitch.states.detector import DetectorState
from newswitch.states.optics import OpticsState


def _digest(payload: Mapping[str, Any]) -> str:
    """A stable hash of `payload`, whatever the order of its keys."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.blake2b(encoded, digest_size=16).hexdigest()


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
        detector_state: DetectorState,
        calibration_state: CalibrationState,
        instrument: Instrument | None = None,
        values: Callable[[], Mapping[str, Any]] | None = None,
        roles: Roles | None = None,
    ) -> None:
        """A manager of `instrument`'s optics, whose current values `values` gives."""
        self.state = state
        self.detector_state = detector_state
        self.calibration_state = calibration_state
        self.instrument = instrument
        self.values = values or dict
        self.table = None if instrument is None else compile_instrument(instrument)
        self.roles = roles
        self._influences: dict[str, frozenset[str]] | None = None
        self._in_focus: dict[str, float] = {}
        self._published: dict[str, str] = {}
        self._refreshing = threading.Lock()

    def _path(self, name: str, values: Mapping[str, Any]) -> LightPath:
        """Every way light takes to the detector `name` under `values`, as the edges say: none,
        where the switches send it elsewhere."""
        assert self.instrument is not None
        seen = self.instrument.sample_of(name, values) is not None
        edges = self.instrument.edges_to(name, values) if seen else []
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
            facts=facts_of(element),
            values={
                variable.name: _reading(variable, values[variable.name])
                for variable in cube.variables.values()
            },
        )

    def get_light_path_for_detector(self, detector: str) -> LightPath:
        """The light path of `detector`, as things are now."""
        return self._path(detector, self.values())

    def snapshot(
        self, path: LightPath, values: Mapping[str, Any] | None = None
    ) -> LightPathSnapshot:
        """`path` under `values`, or as things are now, keyed by what a calibration depends on."""
        assert self.instrument is not None
        if self._influences is None:
            self._influences = influences(self.instrument)
        at = self.values() if values is None else values
        key = _digest(
            {
                # Not its windows: cutting part of an image out does not change where a pixel looks.
                "detector": path.detector,
                **{
                    variable: self._to_step(variable, at[variable])
                    for variable in self._influences[path.detector]
                },
            }
        )
        return LightPathSnapshot(
            key=key,
            hash=_digest(
                {
                    "key": key,
                    **{
                        variable.name: at[variable.name]
                        for variable in self.instrument.variables.values()
                        if variable.verb == "swaps" or variable.cube in self.instrument.sources()
                    },
                }
            ),
            elements=path.elements,
            edges=path.edges,
        )

    def _to_step(self, name: str, value: Any) -> Any:  # noqa: ANN401 - what the variable holds
        """A value as far as it can tell one calibration from another: to within its step.

        Whether a variable changes a pixel at all was found by moving it a step, so less than that
        is the same calibration; and a motor that reports 12.000001 has not moved.
        """
        assert self.instrument is not None
        variable = self.instrument.variables[name]
        return value if variable.verb == "swaps" else round(float(value) / variable.step)

    def predicted(
        self, detector: str, values: Mapping[str, Any] | None = None
    ) -> CalibratedLightPath:
        """What the optics predict for a detector, in the terms of a calibration of it."""
        assert self.table is not None
        answer = self.table.answer(detector, self.values() if values is None else values)
        (xx, xy), (yx, yy) = answer.pixel_to_stage
        return CalibratedLightPath(
            affine_matrix=[
                [xx, xy, 0.0, 0.0],
                [yx, yy, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )

    def scale_under(
        self, detector: str, values: Mapping[str, Any]
    ) -> tuple[CalibratedLightPath, bool]:
        """Where `detector`'s pixels would be under `values`, and whether that was measured."""
        snapshot = self.snapshot(self._path(detector, values), values)
        try:
            return self.calibration_state.get_calibrated_path(snapshot), True
        except ValueError:
            return self.predicted(detector, values), False

    def depth_of_field_um(self, detector: str) -> float:
        """How deep what `detector` sees sharply is, from its objective's NA."""
        assert self.instrument is not None
        return tracing.depth_of_field_um(self.instrument, detector, self.values())

    def found_focus(self, detector: str) -> None:
        """What focuses `detector` is in focus where it is now: defocus counts from there."""
        assert self.roles is not None
        values = self.values()
        sample = self.instrument.seen_sample(detector, values)
        for move in self.roles.focuses(detector, sample):
            self._in_focus[move.name] = float(values[move.name])
        self.refresh()

    def _defocus(self, name: str, values: Mapping[str, Any]) -> float:
        """How far what focuses `name` is from where it is in focus."""
        if self.roles is None:
            return 0.0
        sample = self.instrument.seen_sample(name, values)
        return sum(
            float(values[move.name]) - self._in_focus.get(move.name, float(move.initial))
            for move in self.roles.focuses(name, sample)
        )

    def _detector(self, name: str, values: Mapping[str, Any]) -> DetectorOptics:
        assert self.table is not None and self.instrument is not None
        answer: Answer = self.table.answer(name, values)
        path = self._path(name, values)
        found, calibrated = self.scale_under(name, values)
        matrix = found.affine_matrix
        height, width = self.detector_state.get(name).plane()
        return DetectorOptics(
            name=name,
            sample=self.instrument.seen_sample(name, values),
            calibrated=calibrated,
            pixel_to_stage=[[matrix[0][0], matrix[0][1]], [matrix[1][0], matrix[1][1]]],
            pixel_um=float(np.hypot(matrix[0][0], matrix[1][0])),
            field_width_um=float(np.hypot(matrix[0][0], matrix[1][0])) * width,
            field_height_um=float(np.hypot(matrix[0][1], matrix[1][1])) * height,
            spot_px=answer.spot_px,
            expected_counts=answer.light,
            read_noise_counts=answer.read_noise_counts,
            band_nm=answer.band_nm,
            depth_of_field_um=tracing.depth_of_field_um(self.instrument, name, values),
            defocus_um=self._defocus(name, values),
            plane_um=0.0 if self.roles is None else self.roles.plane_um(name, values),
            path=path,
        )

    def _source(self, name: str, values: Mapping[str, Any]) -> SourceOptics:
        assert self.table is not None and self.instrument is not None
        lit = self.instrument.samples_lit_by(name)
        sides = [
            route[-1].side
            for sample in lit
            for route in self.instrument.routes(self.instrument.illumination, name, sample)
        ]
        side = sides[0] if sides else None
        entries = self.table.states[state_key(self.instrument, values)]
        # What arrives of it at a detector that sees a sample it lights: elsewhere, nothing does.
        seeing, arriving = next(
            (
                (detector, entry["coupling"][name])
                for detector, entry in entries.items()
                if name in entry["coupling"] and self.instrument.sample_of(detector, values) in lit
            ),
            (None, {}),
        )
        band = arriving.get("band_mean_nm")
        found = {
            "name": name,
            "side": side,
            "band_nm": band,
            "band_color": None if band is None else spectrum_color(band),
        }
        sheet = arriving.get("sheet")
        if sheet is not None:
            return SourceOptics(
                shape="sheet",
                field_um=arriving.get("field_um"),
                thickness_um=2.0 * sheet["waist_um"],
                reach_um=sheet["rayleigh_um"],
                along=sheet["along"],
                edge_share=None if seeing is None else self._edge_share(sheet, values, seeing),
                **found,
            )
        if "field_um" in arriving:
            return SourceOptics(shape="field", field_um=arriving["field_um"], **found)
        return SourceOptics(shape="spot", **found)

    def _slot_label(self, name: str, slot: int) -> str:
        """What a swap has in `slot`, as it reads: its name, an open filter as open, else its kind."""
        assert self.instrument is not None
        element = self.instrument.variables[name].slots[slot]
        label = getattr(element, "name", None)
        if label:
            return label
        if isinstance(element, spec.Filter) and element.curve is None:
            return "open"
        return element.kind

    def _edge_share(
        self, sheet: Mapping[str, Any], values: Mapping[str, Any], detector: str
    ) -> float:
        """How strong a sheet still is at the edge of what `detector`, which sees it, sees."""
        assert self.table is not None and self.instrument is not None
        width, height = self.table.answer(detector, values).field_of_view_um
        half = (width if sheet["along"] == "x" else height) / 2.0
        return 1.0 / math.sqrt(1.0 + (half / sheet["rayleigh_um"]) ** 2)

    def _publish(self, field: str, value: Any) -> None:  # noqa: ANN401 - any of the state's fields
        """Set a field of the state, if it changed: what clients hold stays what they hold.

        Compared as text: a published value is turned into another class, so never equals a new one.
        """
        text = json.dumps(value, sort_keys=True, default=asdict)
        if self._published.get(field) != text:
            self._published[field] = text
            setattr(self.state, field, value)

    def refresh(self) -> None:
        """Publish what the optics find under the current values, as far as that changed.

        One at a time, values read to published: two actions finishing together must not leave what
        the older one read behind.
        """
        if self.instrument is None or self.table is None:
            return
        with self._refreshing:
            values = self.values()
            self._publish(
                "detectors",
                {
                    detector.name: self._detector(detector.name, values)
                    for detector in self.detector_state.detectors
                    if detector.delivers_images()
                    and self.instrument.sample_of(detector.name, values) is not None
                },
            )
            self._publish(
                "sources", {name: self._source(name, values) for name in self.instrument.sources()}
            )
            self._publish(
                "elements",
                {
                    name: self._element(name, values)
                    for detector in self.instrument.detectors()
                    if self.instrument.sample_of(detector, values) is not None
                    for edge in self.instrument.edges_to(detector, values)
                    for name in (edge.source, edge.target)
                },
            )
            self._publish(
                "channels",
                [
                    OpticalChannel(
                        source=c.source,
                        detector=c.detector,
                        electrons=c.electrons,
                        sample=c.sample,
                        band_nm=c.band_nm,
                        swaps=[
                            ChannelSwap(name, slot, self._slot_label(name, slot))
                            for name, slot in c.swaps.items()
                        ],
                        field_width_um=c.field_um[0],
                        field_height_um=c.field_um[1],
                    )
                    for c in self.table.channels(values)
                ],
            )
