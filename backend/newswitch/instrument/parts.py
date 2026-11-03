"""An instrument as what the server runs on: what delivers images, and what is wired."""

from __future__ import annotations

from typing import Any, Literal

from newswitch.instrument.errors import SpecError
from newswitch.instrument.hardware import CAMERA_PROTOCOLS
from newswitch.instrument.spec import Drive, Instrument, Probe, Sensor
from newswitch.models.devices import Detector, DetectorAxis


#: How often a probe at a point is read while live (Hz): a temperature does not change by the frame.
POINT_RATE = 1.0


def detectors(instrument: Instrument) -> list[Detector]:
    """One `Detector` per sensor or point detector, all on, with the axes it delivers, and one per
    probe, with what it measures.

    Every axis reads out whole; the binnable ones at the initial binning.
    """
    return [*_light_detectors(instrument), *_probes(instrument)]


def _probes(instrument: Instrument) -> list[Detector]:
    """A probe measures what it says it measures, in its unit, along the axes it has."""
    found = []
    for name in instrument.probes():
        element = instrument.cubes[name].element
        assert isinstance(element, Probe)
        found.append(
            Detector(
                name=name,
                is_active=True,
                data_type="float32",
                quantity=element.measures.quantity,
                unit=element.measures.unit,
                measures_light=False,
                axes=_axes(instrument, name, 1),
                # a probe that samples time is read once a block; one at a point, once a second
                current_frame_rate=POINT_RATE
                if element.sampling is None
                else 1000.0 / element.sampling.block,
            )
        )
    return found


def _axes(instrument: Instrument, name: str, binning: int) -> list[DetectorAxis]:
    """What `name` delivers, as a `Detector` has it."""
    return [
        DetectorAxis(
            name=axis.name,
            domain=axis.domain,
            unit=axis.unit,
            size=axis.size,
            step=axis.step,
            delivered_by=axis.delivered_by,
            binnable=axis.binnable,
            binning=binning if axis.binnable else 1,
        )
        for axis in instrument.detector_axes(name)
    ]


def _light_detectors(instrument: Instrument) -> list[Detector]:
    found = []
    for name in instrument.detectors():
        cube = instrument.cubes[name]
        element = cube.element
        assert element is not None
        binning = cube.tunes.get("binning")
        exposure = cube.tunes.get("exposure")
        gain = cube.tunes.get("gain")
        frame_rate = cube.tunes.get("frame_rate")
        initial_binning = 1 if binning is None else int(binning.initial)
        found.append(
            Detector(
                name=name,
                is_active=True,
                data_type=_data_type(element.readout.bit_depth),
                colors=list(element.colors) if isinstance(element, Sensor) else [],
                axes=_axes(instrument, name, initial_binning),
                current_exposure_ms=None if exposure is None else exposure.initial,
                current_gain=None if gain is None else gain.initial,
                current_frame_rate=None if frame_rate is None else frame_rate.initial,
            )
        )
    return found


def _data_type(bit_depth: int) -> str:
    """The smallest array type that holds `bit_depth` bits."""
    for bits in (8, 16, 32):
        if bit_depth <= bits:
            return f"uint{bits}"
    raise ValueError(f"no array type holds {bit_depth} bits")


def cameras(instrument: Instrument) -> tuple[list[Detector], dict[str, dict[str, Any]]] | None:
    """The detectors to open as cameras, with their vendor options by name.

    The vendor is passed on unchanged: newswitch knows no vendor names, the camera library decides
    which it supports. None when the description wires no camera.
    """
    found = []
    vendor_options: dict[str, dict[str, Any]] = {}
    for detector in _light_detectors(instrument):
        camera = instrument.hardware.cameras.get(detector.name)
        if camera is None:
            continue
        detector.manufacturer = camera.vendor
        detector.connection_type = CAMERA_PROTOCOLS[camera.protocol]
        detector.serial_number = camera.serial_number
        detector.device_index = camera.index
        detector.buffer_size = camera.buffer_size
        detector.store_image_data = camera.store_image_data
        found.append(detector)
        vendor_options[detector.name] = dict(camera.vendor_options)
    return (found, vendor_options) if found else None


def check_wired(
    instrument: Instrument, simulate: Literal["everything", "unwired", "nothing"]
) -> None:
    """Check that what is not to be simulated can be reached.

    With nothing to simulate, a variable with no driver has nothing to take it anywhere, and a
    detector with no camera nothing to deliver its images. A wire with a real end cannot be armed.

    Raises:
        SpecError: Something is not wired; every one is listed.
    """
    problems = [
        f"the probe {name}: no driver reads a probe yet, so it is simulated or nothing"
        for name in instrument.probes()
        if simulate != "everything"
    ]
    if simulate == "nothing":
        problems += [
            f"{variable.name} has no wired actuator (hardware.actuators)"
            for variable in instrument.variables.values()
            if not _keeps_itself(instrument, variable.cube)
            and instrument.hardware.actuators.get(variable.actuator or "") is None
        ]
        problems += [
            f"the detector {name} has no camera (hardware.cameras)"
            for name in instrument.detectors()
            if name not in instrument.hardware.cameras
        ]
    if simulate == "unwired" and instrument.hardware.cameras:
        # One manager runs all the detectors: it would leave these out without a word.
        problems += [
            f"the detector {name} has no camera beside those that do: real and simulated "
            "detectors cannot run together yet"
            for name in instrument.detectors()
            if name not in instrument.hardware.cameras
        ]
    if simulate != "everything":
        # A rig really wired this way while the software steps too would move twice per plane.
        problems += [
            f"{drive.source} -> {drive.target}: no driver can arm this wire yet"
            for drive in instrument.drives
            if simulate == "nothing" or _is_real(instrument, drive)
        ]
    if problems:
        raise SpecError(f"{instrument.name}: {'; '.join(problems)}")


def _is_real(instrument: Instrument, drive: Drive) -> bool:
    """Whether either end of a wire is hardware, with what is unwired simulated."""
    target = instrument.variables.get(drive.target)
    return drive.sender[0] in instrument.hardware.cameras or (
        target is not None and target.actuator in instrument.hardware.actuators
    )


def _keeps_itself(instrument: Instrument, cube: str) -> bool:
    """Whether what a cube's variables are is its detector's: a camera sets its own exposure."""
    return cube in instrument.detectors()
