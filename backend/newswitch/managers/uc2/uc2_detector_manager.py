"""
uc2_detector.py — real-hardware detector manager for UC2 cameras.

Structurally implements the ``DetectorManager`` protocol (like every other
newswitch-py manager). It bridges the SDK-only driver layer (``uc2_devices``)
with the rekuest ``CameraState`` / ``Detector`` data mirror:

    slot -> Uc2Camera   (control, this manager owns it)
    slot -> Detector    (synced state, mirrored into CameraState.detectors)

Boundary reminder: control (connect, exposure, gain, ROI, start/stop) lives
here; the sustained full-rate frame path belongs to the native C++ engine.
``capture_image`` is a snapshot; ``acquire_live`` starts streaming and — once the
native engine exists — hands each camera's ``acquisition_handle()`` to it. A pure
Python fallback loop is provided so this manager already works today at moderate
frame rates without the native engine.

Drop-in for ``VirtualDetectorManager``: place this file at
``newswitch/managers/uc2/uc2_detector.py`` and select it in ``provide_managers``:

    if config.use_virtual_microscope:
        detector = VirtualDetectorManager(camera_state=camera_state, ...)
    else:
        detector = Uc2DetectorManager(camera_state=camera_state,
                                      broadcaster=frame_broadcaster,
                                      settings_path=config.uc2_settings_path)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Sequence

import koil
import numpy as np

from newswitch.protocols.detector import CameraState, Detector
from newswitch.uc2_devices import CameraInfo, Uc2Camera, Uc2DevSettings

if TYPE_CHECKING:  # only needed for type hints, not at runtime
    from newswitch.broadcasters.frame import FrameBroadcaster


class Uc2DetectorManager:
    """Detector manager backed by real UC2 camera drivers (``Uc2Camera``)."""

    state: CameraState
    broadcaster: "FrameBroadcaster"

    def __init__(
        self,
        camera_state: CameraState,
        broadcaster: "FrameBroadcaster",
        *,
        settings_path: str | Path = "uc2DevSettings.json",
        drivers: Sequence[type[Uc2Camera]] = (Uc2Camera,),
        # accepted for drop-in parity with VirtualDetectorManager (unused here):
        stage_state: Any = None,
        illumination_state: Any = None,
        objective_state: Any = None,
        filter_bank_state: Any = None,
    ) -> None:
        self.state = camera_state
        self.broadcaster = broadcaster
        self._drivers = tuple(drivers)
        self._settings = Uc2DevSettings.load(settings_path)
        self._cameras: dict[int, Uc2Camera] = {}
        self._initialize_detectors()

    # ------------------------------------------------------------------ #
    # discovery / lifecycle
    # ------------------------------------------------------------------ #
    def _initialize_detectors(self) -> None:
        """Enumerate cameras, connect them, apply settings, mirror to state.

        Slots are assigned deterministically: a fixed ``slot`` from settings
        wins; otherwise the next free slot in serial-sorted order is used, so a
        restart keeps cameras on stable slots.
        """
        discovered: list[tuple[type[Uc2Camera], Uc2Camera]] = []
        for driver in self._drivers:
            for info in driver.enumerate():
                discovered.append((driver, info))
        discovered.sort(key=lambda t: t[1].serial)

        used_slots: set[int] = set()
        next_auto = 1
        detectors: list[Detector] = []
        for driver, info in discovered:
            cam = driver(info)
            cam.connect()

            cs = self._settings.get_for_serial(info.serial)
            if cs is not None:
                cam.apply_settings(cs)

            if cs is not None and cs.slot is not None:
                slot = cs.slot
            else:
                while next_auto in used_slots:
                    next_auto += 1
                slot = next_auto
            used_slots.add(slot)

            self._cameras[slot] = cam

            fmt = cam.frame_format
            detectors.append(
                Detector(
                    slot=slot,
                    name=info.model,
                    width=fmt.width,
                    height=fmt.height,
                    data_type=fmt.dtype,
                    current_exposure_time=cs.exposure_time_s if cs else 0.01,
                    current_gain=cs.gain if cs else 1.0,
                )
            )

        # Assign the whole list once. The observable ``detectors`` list rejects
        # in-place ``.append`` without the ``camera_parameters`` lock; replacing
        # the attribute during startup is the pattern the other managers use.
        self.state.detectors = detectors

    def shutdown(self) -> None:
        """Stop streaming and release all camera handles (call from lifespan)."""
        try:
            self.broadcaster.stop_broadcasting()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
        for cam in self._cameras.values():
            try:
                if cam.is_running:
                    cam.stop()
            except Exception:  # pragma: no cover
                pass
            try:
                cam.disconnect()
            except Exception:  # pragma: no cover
                pass
        self._cameras.clear()

    # ------------------------------------------------------------------ #
    # DetectorManager protocol
    # ------------------------------------------------------------------ #
    def capture_image(self, slot: int) -> np.ndarray:
        """Capture a single frame (snapshot / moderate rate)."""
        return self._require_camera(slot).grab_frame()

    def activate_detector(self, slot: int) -> Detector:
        """Start acquisition on a detector and mark it active."""
        cam = self._require_camera(slot)
        detector = self.state.get_detector_for_slot(slot)
        if not cam.is_running:
            cam.start()
        detector.is_active = True
        return detector

    def deactivate_detector(self, slot: int) -> None:
        """Stop acquisition on a detector and mark it inactive."""
        cam = self._require_camera(slot)
        detector = self.state.get_detector_for_slot(slot)
        if cam.is_running:
            cam.stop()
        detector.is_active = False

    def update_detector(
        self,
        slot: int,
        exposure_time: Optional[float] = None,
        gain: Optional[float] = None,
    ) -> Detector:
        """Push exposure / gain to the camera and mirror them into state."""
        cam = self._require_camera(slot)
        detector = self.state.get_detector_for_slot(slot)
        if exposure_time is not None:
            cam.set_exposure_time(exposure_time)
            detector.current_exposure_time = exposure_time
        if gain is not None:
            cam.set_gain(gain)
            detector.current_gain = gain
        return detector

    def get_detector_state(self, slot: int) -> Optional[Detector]:
        """Return the detector for ``slot``, or ``None`` if there is none."""
        try:
            return self.state.get_detector_for_slot(slot)
        except ValueError:
            return None

    def list_available_detectors(self) -> list[Detector]:
        """All detectors known to this manager."""
        return self.state.detectors

    def list_active_detectors(self) -> list[Detector]:
        """Currently active detectors."""
        return self.state.get_active_detectors()

    def acquire_live(self) -> None:
        """Start continuous acquisition and broadcast per detector slot.

        Preferred (native) path — once the C++ engine exists:

            self.broadcaster.start_broadcasting()
            for detector in self.state.get_active_detectors():
                cam = self._cameras[detector.slot]
                cam.start()
                native_engine.attach(detector.slot,
                                     cam.acquisition_handle(),
                                     self.broadcaster)  # frames never touch Python
            return

        Python fallback (below): correct for moderate frame rates; do NOT use it
        for the full-rate stream.
        """
        self.broadcaster.start_broadcasting()
        while True:
            if not self.state.is_acquiring:
                koil.sleep(0.1)
                continue
            for detector in self.state.get_active_detectors():
                cam = self._cameras.get(detector.slot)
                if cam is None:
                    continue
                frame = cam.grab_frame()
                self.broadcaster.broadcast_sync(detector.slot, frame)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _require_camera(self, slot: int) -> Uc2Camera:
        cam = self._cameras.get(slot)
        if cam is None:
            raise ValueError(f"No UC2 camera bound to slot {slot}")
        return cam
