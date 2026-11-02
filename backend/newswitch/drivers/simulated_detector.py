"""The detectors of a simulated instrument: sessions, the live loop, binning and windows, as any
detector has them, with images rendered from what its optics do under the current values.

Everything is rendered whole and unbinned, then read out (`newswitch.drivers.readout`): a window
of a scan is the part of it that is scanned, at the same step.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

import koil
import numpy as np

from newswitch.drivers import readout as windows_of
from newswitch.drivers.simulator import Simulator
from newswitch.instrument.spec import Instrument
from newswitch.models.devices import AxisWindow, Detector
from newswitch.protocols.detector import DetectorFrame, DetectorSessionInfo
from newswitch.states.detector import DetectorState

if TYPE_CHECKING:
    from newswitch.protocols.frame_sink import FrameSink

#: Binning factors a simulated detector offers.
BINNINGS = [1, 2, 4]
#: Longest pause of the live loop (s): while idle, and between two paced images.
IDLE_INTERVAL_S = 0.1


@dataclass
class Readout:
    """The acquisition session of one detector; how it is read out is in its `Detector`."""

    session: Optional[DetectorSessionInfo] = None
    """Current or last acquisition session; None before the first acquisition."""
    sequence: int = 0
    """Index of the next image within the session."""
    streaming: bool = False
    """The live loop streams this detector (its session is the live session)."""
    next_due_ns: int = 0
    """When the live loop sends the next image (monotonic ns)."""


def _times_photons(detector: Detector) -> bool:
    """Whether `detector` delivers when its photons arrive, as an axis of its own."""
    return detector.has_axis("m")


def _plane_at(detector: Detector, binning: int) -> tuple[int, int]:
    """The (y, x) size of `detector`'s images in its windows, were it binned by `binning`."""
    y, x = (
        (axis.windowed() or 0) // (binning if axis.binnable else 1)
        for axis in (detector.axis("y"), detector.axis("x"))
    )
    return y, x


class SimulatedDetectorManager:
    """Detectors rendered from the optics, each of the size its description states."""

    #: Called once a value of this part has changed.
    on_change: Callable[[], None] = staticmethod(lambda: None)

    def __init__(
        self,
        instrument: Instrument,
        detector_state: DetectorState,
        detectors: list[Detector],
        values: Callable[[], Mapping[str, Any]],
        step: Callable[[str, float], None],
    ) -> None:
        """The `detectors` of `instrument`.

        Args:
            instrument: What is rendered.
            detector_state: Where they are published.
            detectors: Which to run.
            values: What every variable is now.
            step: Takes a variable to a value, for what a detector's own events drive.
        """
        self.instrument = instrument
        self.state = detector_state
        self.simulator = Simulator(instrument)
        self.values = values
        self.step = step
        self._readouts: dict[str, Readout] = {}
        self._lock = threading.RLock()
        self._closed = False
        for detector in detectors:
            detector.manufacturer = "simulated"
            windows_of.apply(detector, None, self._snap_binning(detector.binning()))
        self.state.detectors = list(detectors)

    # ------------------------------------------------------------- finding them

    def _active(self, name: str | None = None) -> Optional[Detector]:
        for detector in self.state.detectors:
            if detector.is_active and (name is None or detector.name == name):
                return detector
        return None

    def _readout(self, name: str) -> Readout:
        return self._readouts.setdefault(name, Readout())

    # ------------------------------------------------------------- how it is read out

    @staticmethod
    def _snap_binning(binning: int) -> int:
        """The allowed binning factor nearest to `binning`.

        Raises:
            ValueError: A factor < 1.
        """
        if binning < 1:
            raise ValueError(f"binning must be >= 1, got {binning}")
        return min(BINNINGS, key=lambda allowed: abs(allowed - binning))

    # ------------------------------------------------------------- what the sensor sees

    def _whole_sensor(self, detector: Detector) -> np.ndarray:
        """The whole sensor as ``(y, x)``, before its windows are cut out and it is binned.

        What a color camera shows on its own (the live view, an autofocus) is the mean of its
        colors: everything that expects one image gets one.
        """
        values = self.values()
        if detector.colors:
            colors = self.simulator.render_colors(detector.name, values)
            mean = np.mean(list(colors.values()), axis=0)
            return np.rint(mean).astype(detector.data_type)
        if _times_photons(detector):
            histogram = self.simulator.render_microtime(detector.name, values)
            top = np.iinfo(detector.data_type).max
            return histogram.sum(axis=0).clip(0, top).astype(detector.data_type)
        return self.simulator.render(detector.name, values)

    # ------------------------------------------------------------- sessions

    def _start_session(self, detector: Detector, readout: Readout) -> None:
        """Begin a new acquisition session of `detector`; its images count from 0 again."""
        height, width = detector.plane()
        readout.session = DetectorSessionInfo(
            detector_id=f"simulated-{detector.name}",
            dims=["y", "x"],
            shape=[height, width],
            dtype=detector.data_type,
            frame_bytes=width * height * np.dtype(detector.data_type).itemsize,
            slot_count=1,
            start_wall_ns=time.time_ns(),
            start_mono_ns=time.monotonic_ns(),
            settings={
                "exposure_time_ms": detector.current_exposure_ms,
                "gain_db": detector.current_gain,
                "frame_rate_per_sec": detector.current_frame_rate,
                **windows_of.settings(detector),
            },
            recording_file=None,
        )
        readout.sequence = 0

    def _next_frame(self, detector: Detector, readout: Readout) -> DetectorFrame:
        """Render the next image of the detector's current session."""
        data = windows_of.read_out(self._whole_sensor(detector), detector, ("y", "x"))
        time_ns = time.monotonic_ns()
        sequence = readout.sequence
        readout.sequence += 1
        session = readout.session
        return DetectorFrame(
            detector=detector.name,
            data=data,
            sequence=sequence,
            time_ns=time_ns,
            wall_time_ns=None if session is None else session.wall_time_ns(time_ns),
        )

    def _set_streaming(self, detector: Detector, readout: Readout, streaming: bool) -> None:
        """Mark whether the live loop streams `detector`; it counts as recording then."""
        readout.streaming = streaming
        detector.is_recording = streaming

    def _end_live_sessions(self) -> None:
        """Mark every detector as not streaming; its last session stays readable."""
        with self._lock:
            for detector in self.state.detectors:
                readout = self._readout(detector.name)
                if readout.streaming:
                    self._set_streaming(detector, readout, False)

    # ------------------------------------------------------------- the protocol

    def activate_detector(self, name: str) -> Detector:
        """Turn the detector called `name` on."""
        detector = self.state.get(name)
        detector.is_active = True
        return detector

    def deactivate_detector(self, name: str) -> None:
        """Turn the detector called `name` off."""
        self.state.get(name).is_active = False

    def update_detector(
        self,
        name: str,
        exposure_ms: float | None = None,
        gain: float | None = None,
        frame_rate: float | None = None,
        binning: int | None = None,
        windows: list[AxisWindow] | None = None,
    ) -> Detector:
        """Change how a detector reads out; None keeps a setting.

        A new binning or window changes its image size and, while streaming, starts a new session
        (as a camera restarts).

        Raises:
            ValueError: No such detector, a frame rate < 0, a binning < 1, or windows
                `newswitch.drivers.readout.check_windows` refuses.
        """
        detector = self.state.get(name)
        if frame_rate is not None and frame_rate < 0:
            raise ValueError(f"frame rate must be >= 0, got {frame_rate}")
        with self._lock:
            readout = self._readout(name)
            if binning is not None or windows is not None:
                snapped = None if binning is None else self._snap_binning(binning)
                windows_of.apply(detector, windows, snapped)
                if readout.streaming:
                    self._start_session(detector, readout)
            if exposure_ms is not None:
                detector.current_exposure_ms = exposure_ms
            if gain is not None:
                detector.current_gain = gain
            if frame_rate is not None:
                detector.current_frame_rate = None if frame_rate == 0 else frame_rate
        self.on_change()
        return detector

    def plane_under(self, name: str, binning: float | None = None) -> tuple[int, int]:
        """The (y, x) size of its images, at `binning` or the one it has now."""
        detector = self.state.get(name)
        factor = detector.binning() if binning is None else self._snap_binning(int(binning))
        return _plane_at(detector, factor)

    def get_detector_state(self, name: str) -> Optional[Detector]:
        """The detector called `name`, if there is one."""
        return next((d for d in self.state.detectors if d.name == name), None)

    def get_image_info(self, name: str) -> Optional[DetectorSessionInfo]:
        """The metadata of the current or last acquisition session; None before the first one.

        Raises:
            ValueError: No such detector.
        """
        self.state.get(name)
        with self._lock:
            return self._readout(name).session

    def list_available_detectors(self) -> list[Detector]:
        """All detectors."""
        return self.state.detectors

    def list_active_detectors(self) -> list[Detector]:
        """The detectors that are on."""
        return self.state.get_active_detectors()

    def capture_image(self, name: str | None = None) -> DetectorFrame:
        """One image from a detector, or the first that is on; outside of the live stream, every
        snapshot is a session of its own.

        Raises:
            ValueError: That detector is not on.
        """
        detector = self._active(name)
        if detector is None:
            raise ValueError(f"No active detector {name or ''}".rstrip())
        with self._lock:
            readout = self._readout(detector.name)
            if not readout.streaming:
                self._start_session(detector, readout)
            return self._next_frame(detector, readout)

    def capture_channels(self, name: str) -> np.ndarray:
        """One exposure along every axis but ``z``: ``(c, y, x)`` in the order of its `colors`,
        ``(m, y, x)`` timing its photons, ``(y, x)`` otherwise."""
        detector = self.state.get(name)
        values = self.values()
        if _times_photons(detector):
            histogram = self.simulator.render_microtime(name, values)
            return windows_of.read_out(histogram, detector, ("m", "y", "x"))
        if not detector.colors:
            return self.capture_image(name).data
        colors = self.simulator.render_colors(name, values)
        stacked = np.stack([colors[color] for color in detector.colors])
        return windows_of.read_out(stacked, detector, ("c", "y", "x"))

    def capture_stack(self, name: str, planes: int) -> Iterator[np.ndarray]:
        """Each event of the detector steps what its wire reaches; the sweep ends on the last plane.

        Raises:
            ValueError: Its events step nothing.
        """
        drive = self.instrument.z_drive(name)
        axes = [axis for axis in self.state.get(name).axes if axis.name == "z"]
        if drive is None or not axes:
            raise ValueError(f"Detector {name} delivers no z")
        first = self.values()[drive.target]
        for plane in range(planes):
            self.step(drive.target, first + plane * axes[0].step)
            yield self.capture_channels(name)

    def acquire_live(self, sink: FrameSink) -> None:
        """Run the live loop until `close`.

        While `DetectorState.is_acquiring` is set, renders an image of every active detector and
        sends it to `sink` under its name: as fast as frames render, or paced by its frame rate.
        Each streams in a session of its own.
        """
        sink.start_broadcasting()
        while not self._closed:
            if not self.state.is_acquiring:
                self._end_live_sessions()
                koil.sleep(IDLE_INTERVAL_S)
                continue
            wait_s = self._stream_due_frames(sink)
            if wait_s > 0:
                koil.sleep(wait_s)

    def _stream_due_frames(self, sink: FrameSink) -> float:
        """Send `sink` an image of every active detector that is due.

        Returns:
            Seconds until the next image is due, at most `IDLE_INTERVAL_S`.
        """
        wait_s = IDLE_INTERVAL_S
        with self._lock:
            if not self.state.is_acquiring:  # stopped since the loop looked
                return 0.0
            for detector in self.state.detectors:
                readout = self._readout(detector.name)
                if not detector.is_active:
                    if readout.streaming:
                        self._set_streaming(detector, readout, False)
                    continue
                if not readout.streaming:
                    self._set_streaming(detector, readout, True)
                    readout.next_due_ns = 0
                    self._start_session(detector, readout)
                now_ns = time.monotonic_ns()
                if now_ns >= readout.next_due_ns:
                    frame = self._next_frame(detector, readout)
                    sink.broadcast_sync(detector.name, frame.data)
                    rate = detector.current_frame_rate
                    period_ns = 0 if rate is None else int(1e9 / rate)
                    readout.next_due_ns = now_ns + period_ns
                remaining_s = (readout.next_due_ns - time.monotonic_ns()) / 1e9
                wait_s = min(wait_s, max(0.0, remaining_s))
        return wait_s

    def stop_acquire_live(self) -> None:
        """Stop the live stream now; `acquire_live` streams again once `is_acquiring` is set."""
        with self._lock:
            self.state.is_acquiring = False
            self._end_live_sessions()

    def close(self) -> None:
        """End `acquire_live`; calling it again does nothing."""
        self._closed = True
        self._end_live_sessions()
