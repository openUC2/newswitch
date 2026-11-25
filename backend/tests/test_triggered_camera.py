"""A camera an acquisition triggers: fired for each frame, held acquiring for the whole run (with
uc2_cam_py's simulated camera, given a software trigger)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

uc2_cam_py = pytest.importorskip("uc2_cam_py")

from newswitch.drivers.uc2.uc2_detector import UC2DetectorManager  # noqa: E402
from newswitch.instrument import parts as instrument_parts  # noqa: E402
from newswitch.instrument import spec  # noqa: E402
from newswitch.states.detector import DetectorState  # noqa: E402

FRAME = Path(__file__).parent.parent / "instruments" / "johannes-frame"


class Triggered:
    """A camera with a software trigger: uc2_cam_py's simulated one (which runs free regardless)."""

    def __init__(self, camera: Any) -> None:  # noqa: ANN401
        self._camera = camera
        self.trigger_on = False
        self.fired = 0

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return getattr(self._camera, name)

    def set_software_trigger(self, on: bool) -> bool:
        self.trigger_on = on
        return True

    def fire(self) -> bool:
        assert self.trigger_on, "fired while it runs free"
        self.fired += 1
        return True


@pytest.fixture
def manager(tmp_path: Path) -> Iterator[UC2DetectorManager]:
    """johannes-frame's camera, simulated by uc2_cam_py: as large as the real one."""
    found = instrument_parts.cameras(spec.load(FRAME))
    assert found is not None
    detectors, _ = found
    detector = detectors[0]
    detector.manufacturer, detector.serial_number, detector.connection_type = "Simulated", None, None
    made = UC2DetectorManager(
        detector_state=DetectorState(),
        cameras=[detector],
        vendor_options={
            detector.name: {"sensor_width": 3072, "sensor_height": 2048, "frame_rate": 100.0}
        },
        recording_dir=tmp_path,
    )
    made.activate_detector(detector.name)
    yield made
    made.close()


def test_a_triggered_camera_is_fired_for_each_capture_and_held_until_ended(
    manager: UC2DetectorManager,
) -> None:
    """An acquisition keeps the camera acquiring, triggered, rather than starting it for each
    frame; every capture fires one, and its frame stays in its slot until the next (`held`)."""
    name = manager.state.detectors[0].name
    cam = manager._cameras[name]
    assert manager.begin_triggered(name) is False  # the simulated camera has no trigger
    cam.camera = Triggered(cam.camera)
    assert manager.begin_triggered(name) is True
    assert cam.camera.trigger_on and cam.camera.is_recording
    frames = [manager.capture_frame(name) for _ in range(3)]
    assert cam.camera.fired == 3 and all(frame.held for frame in frames)
    assert cam.camera.is_recording  # not stopped between captures
    assert manager.capture_image(name).data.max() > 0 and cam.camera.fired == 4
    manager.end_triggered(name)
    assert not cam.camera.trigger_on and not cam.camera.is_recording
    assert not manager.capture_frame(name).held and cam.camera.fired == 4  # runs free again
