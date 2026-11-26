"""Measuring a holder's mount from a calibration slide (newswitch.calibration.mount)."""

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import koil
import numpy as np
import pytest

from newswitch.calibration import mount as mc
from newswitch.calibration.manager import CalibrationManager
from newswitch.calibration.states import CalibrationState
from newswitch.calibration.store import CalibrationStore
from newswitch.instrument import spec
from newswitch.instrument.errors import SpecError
from newswitch.instrument.spec import Mount

FRAME = Path(__file__).parent.parent / "instruments" / "johannes-frame"


def disc(shape: tuple[int, int], x: float, y: float, radius: float = 40.0) -> np.ndarray:
    """A black image with a bright disc whose middle is (x, y) from the image's middle."""
    height, width = shape
    ys, xs = np.mgrid[0:height, 0:width]
    image = np.full(shape, 8, dtype=np.uint16)
    inside = (xs - (width - 1) / 2 - x) ** 2 + (ys - (height - 1) / 2 - y) ** 2 <= radius**2
    image[inside] = 4088
    return image


# --- the pure parts ----------------------------------------------------------------------------


def test_a_bright_disc_is_found_where_it_is() -> None:
    spot = mc.bright_spot(disc((300, 400), 30.0, -20.0))
    assert spot is not None and not spot.cut
    assert (spot.x, spot.y) == (pytest.approx(30.0, abs=0.1), pytest.approx(-20.0, abs=0.1))
    assert spot.diameter == pytest.approx(80.0, rel=0.05)


def test_black_or_an_evenly_lit_field_has_no_disc() -> None:
    assert mc.bright_spot(np.full((100, 100), 8, dtype=np.uint16)) is None
    lit = np.random.default_rng(0).normal(600, 30, (100, 100))
    assert mc.bright_spot(lit) is None


def test_a_disc_the_edge_cuts_says_so() -> None:
    spot = mc.bright_spot(disc((200, 200), 95.0, 0.0))
    assert spot is not None and spot.cut


def test_the_search_goes_out_ring_by_ring() -> None:
    offsets = list(mc.spiral(2000.0, 1000.0))
    assert offsets[0] == (0.0, 0.0) and len(offsets) == 25
    assert max(abs(c) for o in offsets[:9] for c in o) == 1000.0


def test_the_mount_is_where_the_stage_is_less_the_mark() -> None:
    assert mc.mount_from((18326.0, 42108.0), (18.4, 40.6), 0.0) == mc.mount_of(-0.074, 1.508)
    turned = mc.mount_from((1000.0, 1000.0), (1.0, 0.0), 90.0)
    assert (turned.x, turned.y) == (pytest.approx(1.0), pytest.approx(0.0))


def test_what_is_kept_is_of_one_design(tmp_path: Path) -> None:
    """A store of another design is stale: nothing of it is applied, and the next calibration
    replaces it."""
    instrument = spec.load(FRAME)
    kept = keeping(instrument, tmp_path)
    nominal = instrument.sample_holder("stage").holders["slides"].mount
    kept.set_mount("stage", "slides", mc.mount_of(nominal.x + 0.1, nominal.y - 0.2))
    assert not kept.state.stale and kept.state.stored_design == instrument.design_hash()
    path = kept.store.path
    path.write_text(path.read_text().replace(instrument.design_hash(), "another-design"))
    later = keeping(instrument, tmp_path)
    assert later.state.stale and later.state.stored_design == "another-design"
    assert later.mount("stage", "slides") is None and later.state.mounts == []
    later.set_mount("stage", "slides", mc.mount_of(nominal.x, nominal.y))
    assert not later.state.stale and later.store.load().design == instrument.design_hash()


def test_without_a_store_a_calibration_holds_until_the_next_start() -> None:
    instrument = spec.load(FRAME)
    kept = CalibrationManager(CalibrationState(), instrument)
    nominal = instrument.sample_holder("stage").holders["slides"].mount
    assert kept.set_mount("stage", "slides", mc.mount_of(nominal.x + 0.1, nominal.y)) is None
    assert kept.mount("stage", "slides").x == pytest.approx(nominal.x + 0.1)


# --- the description ------------------------------------------------------------------------------


def test_the_frame_states_its_holder_and_where_its_calibration_mark_is() -> None:
    holding = spec.load(FRAME).sample_holder("stage")
    assert holding.mounted == "slides" and holding.calibration is not None
    assert holding.mark_on_holder() == (pytest.approx(18.4), pytest.approx(40.6))
    assert holding.calibration.home == ["Z", "X", "Y", "A"]


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"holder": "plate"}, "none of the holders"),
        ({"at": "slot:A9"}, "no place of it"),
        ({"mark": "pinhole:D1"}, "no place of it"),
    ],
)
def test_a_calibration_names_what_is_there(tmp_path: Path, change: dict, problem: str) -> None:
    import yaml

    copy = tmp_path / "frame"
    shutil.copytree(FRAME, copy)
    path = copy / "microscope.yml"
    description = yaml.safe_load(path.read_text())
    description["cubes"]["stage"]["element"]["calibration"].update(change)
    path.write_text(yaml.safe_dump(description))
    with pytest.raises(SpecError, match=problem):
        spec.load(copy)


# --- the routine, against a stage whose holder sits elsewhere than described -------------------


class Frame:
    """The frame's stage and camera: a pinhole at `mark_um` on the stage, an image 0.6 um a pixel,
    turned 180 degrees (as this frame's camera is), centred where the stage is."""

    def __init__(self, mark_um: tuple[float, float]) -> None:
        self.instrument = spec.load(FRAME)
        self.mark_um = np.array(mark_um)
        self.position = {"stage.x": 0.0, "stage.y": 0.0, "stage.z": 0.0}
        self.settings: dict[str, float] = {"led.power": 0.0, "camera.exposure": 100.0}
        self.homed: list[str] = []
        self.mounts: list[Mount] = []
        self.captures = 0

    # Values
    def snapshot(self) -> dict[str, float]:
        return {**self.position, **self.settings}

    def set(self, targets: dict[str, float], relative: bool = False, task: Any = None) -> None:
        for name, value in targets.items():
            (self.position if name in self.position else self.settings)[name] = value

    # the detector
    def capture_image(self, name: str) -> Any:  # noqa: ANN401
        self.captures += 1
        here = np.array([self.position["stage.x"], self.position["stage.y"]])
        x, y = -(self.mark_um - here) / 0.6  # turned 180 degrees
        return SimpleNamespace(data=disc((2048, 3072), x, y, radius=300.0))

    def activate_detector(self, name: str) -> None:
        pass

    # the bus
    async def ahome_axis(self, axis: str) -> None:
        self.homed.append(axis)


class Space:
    def __init__(self, frame: Frame) -> None:
        holding = frame.instrument.sample_holder("stage")
        self.mounted = holding.holders["slides"]
        self.frame = frame
        self.detector_state = SimpleNamespace(
            detectors=[SimpleNamespace(name="camera", is_active=True, delivers_images=lambda: True)]
        )

    def one_sample(self, sample: Any) -> str:  # noqa: ANN401
        return "stage"

    def mounted_holder(self, holder: str, sample: str) -> Any:  # noqa: ANN401
        return self.mounted

    def set_mount(self, holder: str, mount: Mount, sample: str) -> None:
        self.frame.mounts.append(mount)

    def sample_of(self, detector: str) -> str:
        return "stage"


class Task:
    """A task whose holds are decided as `approve` says; it keeps what it was asked."""

    def __init__(self, frame: Frame, approve: bool = True) -> None:
        self.frame, self.approve = frame, approve
        self.holds: list[tuple[str, Any, tuple[float, float]]] = []

    def progress(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        pass

    def hold(self, message: str, prompt: Any = None) -> Any:  # noqa: ANN401
        where = (self.frame.position["stage.x"], self.frame.position["stage.y"])
        self.holds.append((message, prompt, where))
        assert self.frame.settings["led.power"] > 0  # the light is on while it holds
        return SimpleNamespace(approved=self.approve)


def run(
    frame: Frame,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task: Task | None = None,
    state: Any = None,  # noqa: ANN401
) -> Any:  # noqa: ANN401
    from newswitch.calibration.states import MountCalibrationState
    from newswitch.drivers.uc2.boards import UC2Boards
    from newswitch.states.uc2 import UC2State

    task = task or Task(frame)
    state = state if state is not None else MountCalibrationState()
    kept = keeping(frame.instrument, tmp_path)
    with koil.Koil():
        boards = UC2Boards({"uc2": frame}, UC2State())  # type: ignore[dict-item]
        result = mc.calibrate_mount(Space(frame), frame, frame, boards, kept, state, task)  # type: ignore[arg-type]
    return result, kept


def keeping(instrument: spec.Instrument, tmp_path: Path) -> CalibrationManager:
    """What is calibrated of `instrument`, kept in a store under `tmp_path`."""
    return CalibrationManager(
        CalibrationState(), instrument, CalibrationStore(tmp_path / "calibration", instrument.name)
    )


def test_the_mount_is_measured_used_and_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the holder sits at (0.3, 1.2) mm: its slot 1 pinhole at (18.7, 41.8) mm on the stage, some
    # 0.4 mm from where the description puts it
    frame = Frame(mark_um=(18700.0, 41800.0))
    result, copy = run(frame, tmp_path, monkeypatch)
    assert frame.homed == ["Z", "X", "Y", "A"]
    assert (result.x_mm, result.y_mm) == (pytest.approx(0.3, abs=0.002), pytest.approx(1.2, abs=0.002))
    described = frame.instrument.sample_holder("stage").holders["slides"].mount
    assert result.shift_um == [
        pytest.approx((0.3 - described.x) * 1e3, abs=2),
        pytest.approx((1.2 - described.y) * 1e3, abs=2),
    ]
    assert result.pixel_um == pytest.approx(0.6, rel=0.01)
    assert frame.mounts == [mc.mount_of(result.x_mm, result.y_mm)]
    # kept as how far it is from the design's mount, which stays as it is
    assert result.saved_to == str(copy.store.path)
    [offset] = copy.store.load().mounts
    assert (offset.offset_x_um, offset.offset_y_um) == (
        pytest.approx(result.shift_um[0], abs=0.01),
        pytest.approx(result.shift_um[1], abs=0.01),
    )
    again = keeping(frame.instrument, tmp_path).mount("stage", "slides")
    assert (again.x, again.y) == (pytest.approx(result.x_mm), pytest.approx(result.y_mm))
    # the light and the exposure are taken back; the focus too
    assert frame.settings == {"led.power": 0.0, "camera.exposure": 100.0}
    assert frame.position["stage.z"] == 0.0


def test_a_mark_further_off_is_searched_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 2.6 and 1.9 mm from where the description puts it: not in the first image
    frame = Frame(mark_um=(18400.0 + 2600.0, 40600.0 - 1900.0))
    result, _ = run(frame, tmp_path, monkeypatch)
    assert (result.x_mm, result.y_mm) == (pytest.approx(2.6, abs=0.002), pytest.approx(-1.9, abs=0.002))


def test_no_mark_says_where_it_was_looked_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame = Frame(mark_um=(90000.0, 10000.0))
    with pytest.raises(ValueError, match="no mark within 4 mm"):
        run(frame, tmp_path, monkeypatch)
    assert frame.settings == {"led.power": 0.0, "camera.exposure": 100.0}


def test_it_holds_once_homed_with_the_light_where_the_mark_should_be(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from newswitch.calibration.states import MountCalibrationState

    frame = Frame(mark_um=(18700.0, 41800.0))
    task, state = Task(frame), MountCalibrationState()
    result, _ = run(frame, tmp_path, monkeypatch, task=task, state=state)
    [(message, prompt, where)] = task.holds
    assert "Homed (Z, X, Y, A)" in message and "slot:A1" in message
    assert prompt.title.startswith("Homed")
    described = frame.instrument.sample_holder("stage").holders["slides"].mount
    assert where == (pytest.approx(18400 + described.x * 1e3), pytest.approx(40600 + described.y * 1e3))
    # the panel's state: done, with what it found
    assert (state.busy, state.waiting, state.error, state.progress) == (False, None, None, 100)
    assert state.last == result and (state.mount_x_mm, state.mount_y_mm) == (result.x_mm, result.y_mm)


def test_a_denied_hold_stops_it_before_anything_is_looked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from newswitch.calibration.states import MountCalibrationState

    frame = Frame(mark_um=(18700.0, 41800.0))
    state = MountCalibrationState()
    with pytest.raises(ValueError, match="denied"):
        run(frame, tmp_path, monkeypatch, task=Task(frame, approve=False), state=state)
    assert frame.captures == 0 and frame.mounts == []
    assert frame.settings == {"led.power": 0.0, "camera.exposure": 100.0}
    assert (state.busy, state.step) == (False, "failed") and "denied" in (state.error or "")


def test_the_frame_starts_with_its_calibration_in_the_state() -> None:
    import asyncio

    from newswitch.microscope.startup import provide_mount_calibration

    instrument = spec.load(FRAME)
    space = SimpleNamespace(mounted_holder=lambda holder, sample: instrument.sample_holder(sample).holders[holder])
    run = SimpleNamespace(instrument=instrument, microscope=SimpleNamespace(space=space))
    state = asyncio.run(provide_mount_calibration(run))  # type: ignore[arg-type]
    assert (state.sample, state.holder, state.at, state.mark) == ("stage", "slides", "slot:A1", "pinhole:B1")
    assert state.slide.startswith("openUC2's pinhole slide") and not state.busy
