"""What is wired to what: components, the wires between them, and the detectors that makes."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from newswitch.instrument import parts, spec
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.acquisition import StreamIllumination, Streams
from tests.conftest import run_settings
from tests.test_multidimensional_acquisition import RecordingStore, acquire, plan

BASE = {
    "spec": "newswitch/instrument/v0",
    "name": "wired",
    "cubes": {
        "laser": {
            "element": {
                "kind": "source",
                "wavelength": "488 nm",
                "width": "2 nm",
                "max_power": "50 mW",
            },
            "signals": {"in": ["power"]},
            "tunes": {"power": {"initial": 10.0, "step": 1.0, "units": "mW"}},
        },
        "stage": {
            "element": {
                "kind": "sample",
                "simulations": {
                    "beads": {
                        "fluorophore": {
                            "excitation": "488 nm",
                            "excitation_width": "20 nm",
                            "emission": "515 nm",
                            "emission_width": "25 nm",
                            "quantum_yield": 0.02,
                        },
                        "transmit": 0.9,
                        "reflect": 0.001,
                        "pattern": {"beads": 3600, "radius": "10 um"},
                    }
                },
            },
            "signals": {"in": ["z"]},
            "moves": {
                "x": {"along": "x", "initial": 0.0, "step": 10.0, "min": -5000.0, "max": 5000.0},
                "y": {"along": "y", "initial": 0.0, "step": 10.0, "min": -5000.0, "max": 5000.0},
                "z": {"along": "axis", "initial": 0.0, "step": 10.0, "min": -50.0, "max": 50.0},
            },
        },
        "objective": {"element": {"kind": "lens", "f": "20 mm", "na": 0.25}},
        "tube": {"element": {"kind": "lens", "f": "200 mm"}},
        "camera": {
            "component": "generic-camera-512",
            "tunes": {
                "exposure": {"initial": 100.0, "step": 10.0, "units": "ms"},
                "gain": {"initial": 0.0, "step": 1.0, "units": "dB"},
                "binning": {"initial": 1, "step": 1},
            },
        },
    },
    "illumination": [{"from": "laser", "to": "stage", "side": "transmitted"}],
    "detection": [
        {"from": "stage", "to": "objective", "distance": "focus"},
        {"from": "objective", "to": "tube", "distance": "100 mm"},
        {"from": "tube", "to": "camera", "distance": "focus"},
    ],
    "parts": {
        "stage": "stage",
        "sources": {1: {"cube": "laser", "full_intensity": 100.0}},
        "detectors": {1: {"cube": "camera", "frame_rate": "30 Hz"}},
    },
    "drives": [{"from": "camera.frame", "to": "stage.z", "by": "2 um"}],
    "settings": {
        "use_virtual_microscope": True,
        "simulation": "beads",
        "db_path": "agent.db",
        "image_dir": "/tmp/newswitch/images",
        "cache_dir": "/tmp/newswitch/cache",
        "camera_recording_dir": None,
        "camera_debug_window": False,
    },
}


def described(tmp_path: Path, change: Callable[[dict[str, Any]], Any] = lambda _: None) -> Path:
    """A folder with the wired description, with `change` made to it."""
    data = copy.deepcopy(BASE)
    change(data)
    folder = tmp_path / "wired"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / spec.DESCRIPTION).write_text(yaml.safe_dump(data))
    return folder


def compiled(tmp_path: Path) -> Microscope:
    """The simulated microscope of the wired description."""
    return build_microscope(run_settings(tmp_path), spec.load(described(tmp_path)))


def stream() -> Streams:
    """The laser for the camera."""
    return Streams(
        detectors=["camera"],
        illuminations=[StreamIllumination(source="laser", wavelength=488.0, intensity=1.0)],
    )


# --- when a description is parsed


def test_every_entry_of_the_library_validates() -> None:
    """A library nobody can load would only show when an instrument names it."""
    assert spec.component_names()
    for name in spec.component_names():
        assert spec.component_data(name)["spec"].startswith(spec.COMPONENT_SPEC)


def test_a_component_makes_up_a_cube(tmp_path: Path) -> None:
    """Its element and its signals, and the name it came from."""
    cube = spec.load(described(tmp_path)).cubes["camera"]
    assert cube.component == "generic-camera-512"
    assert isinstance(cube.element, spec.Sensor) and cube.element.axes["x"].size == 512
    assert set(cube.signals.outputs) == {"frame", "exposing"}
    assert cube.signals.inputs == ("trigger",)


@pytest.mark.parametrize(
    "change, finding",
    [
        (lambda d: d["cubes"]["camera"].update(component="nothing"), "no component 'nothing'"),
        (lambda d: d["cubes"]["camera"].update(element={"kind": "sample"}), "already states"),
        (lambda d: d["cubes"]["camera"].update(signals={}), "already states"),
        (lambda d: d["cubes"]["stage"].update(signals={"out": {"x": {"axes": ["q"]}}}), "axes"),
        (lambda d: d["cubes"]["stage"].update(signals={"sideways": []}), "sideways"),
        (lambda d: d["drives"].append({"from": "nothing.frame", "to": "stage.z"}), "'nothing'"),
        (lambda d: d["drives"].append({"from": "camera.flash", "to": "laser.power"}), "'flash'"),
        (lambda d: d["drives"].append({"from": "camera.frame", "to": "laser.dim"}), "'dim'"),
        (lambda d: d["drives"].append({"from": "camera.frame", "to": "camera.frame"}), "accepts"),
        (lambda d: d["drives"][0].pop("by"), "needs 'by'"),
        (lambda d: d["drives"][0].update(by="2 mW"), "by"),
        (
            lambda d: d["drives"].append(
                {"from": "camera.exposing", "to": "laser.power", "by": 1.0}
            ),
            "takes no 'by'",
        ),
        (lambda d: d["drives"].append(dict(d["drives"][0])), "stepped by two wires"),
        (
            lambda d: (
                d["cubes"]["stage"]["signals"]["in"].append("x"),
                d["drives"].append({"from": "camera.frame", "to": "stage.x", "by": 1.0}),
            ),
            "only the stage's z",
        ),
        (
            lambda d: (
                d["cubes"]["laser"]["signals"].update(out={"sync": {}}),
                d["drives"].__setitem__(0, {"from": "laser.sync", "to": "stage.z", "by": 1.0}),
            ),
            "is no detector",
        ),
    ],
)
def test_what_cannot_be_wired_is_refused_when_parsed(
    tmp_path: Path, change: Callable[[dict[str, Any]], Any], finding: str
) -> None:
    """Naming the part and the signal."""
    with pytest.raises(spec.SpecError, match=finding):
        spec.load(described(tmp_path, change))


def test_every_component_problem_is_listed_at_once(tmp_path: Path) -> None:
    """So that fixing a file takes one round."""

    def change(data: dict[str, Any]) -> None:
        data["cubes"]["camera"]["component"] = "nothing"
        data["cubes"]["tube"]["component"] = "neither"

    with pytest.raises(spec.SpecError) as info:
        spec.load(described(tmp_path, change))
    assert "cubes.camera" in str(info.value) and "cubes.tube" in str(info.value)


def test_a_wire_is_refused_on_real_hardware(tmp_path: Path) -> None:
    """A rig really wired so, with the software stepping too, would move twice per plane."""
    with pytest.raises(spec.SpecError, match="no driver can arm this wire"):
        parts.check_wired(spec.load(described(tmp_path)))


# --- the logical detectors


def test_a_camera_alone_delivers_its_sensor(tmp_path: Path) -> None:
    """Without a wire: two axes, each with its size."""
    instrument = spec.load(described(tmp_path, lambda d: d.pop("drives")))
    axes = instrument.detector_axes("camera")
    assert [(axis.name, axis.size) for axis in axes] == [("y", 512), ("x", 512)]


def test_a_wire_gives_a_camera_a_z_axis(tmp_path: Path) -> None:
    """Whose size each acquisition sets, and whose step is the wire's."""
    z, y, x = spec.load(described(tmp_path)).detector_axes("camera")
    assert (z.name, z.size, z.step) == ("z", None, 2.0)
    assert z.delivered_by == "camera.frame -> stage.z"
    assert (y.name, x.name) == ("y", "x")


def test_a_color_camera_delivers_its_colors() -> None:
    """Already: an axis of its own."""
    instrument = spec.load(Path(__file__).parent.parent / "instruments" / "rgb-camera")
    assert [axis.name for axis in instrument.detector_axes("camera")] == ["c", "y", "x"]


# --- a stack the detector sweeps


class CountingMoves:
    """Counts what the routine asks of a stage."""

    def __init__(self, m: Microscope) -> None:
        """Between the routine and the stage of `m`."""
        self.moves: list[float | None] = []
        self.original = m.stage.move

        def move(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            self.moves.append(kwargs.get("z"))
            return self.original(*args, **kwargs)

        m.stage.move = move  # type: ignore[method-assign]


class RecordingZ(RecordingStore):
    """Remembers where the stage really was at each image."""

    def __init__(self, m: Microscope) -> None:
        """Reading the stage of `m`."""
        super().__init__()
        self.m = m

    def state(self) -> dict[str, float]:
        """Where the stage is now."""
        return {"stage.z": self.m.stage_state.z}


def test_a_swept_stack_takes_no_software_steps(tmp_path: Path) -> None:
    """The stage goes to the first plane and the wire does the rest, on the planes asked for."""
    m = compiled(tmp_path)
    counting = CountingMoves(m)
    store = acquire(m, plan([stream()], planes=[0.0, 2.0, 4.0]), RecordingZ(m))
    assert counting.moves == [0.0, 0.0]  # the position, and the first plane
    acquired = store.published[0]
    assert acquired.data.shape == (1, 1, 3, 512, 512)
    assert [plane.state["stage.z"] for plane in acquired.planes] == [0.0, 2.0, 4.0]


def test_a_swept_stack_is_the_stack_software_would_take(tmp_path: Path) -> None:
    """Image for image, from the same noise: only who steps the stage differs."""
    swept = compiled(tmp_path / "swept")
    planes = [0.0, 2.0, 4.0]
    wired = acquire(swept, plan([stream()], planes=planes)).published[0].data

    plain = compiled(tmp_path / "plain")
    for axis in plain.camera_state.detectors:
        axis.axes = [item for item in axis.axes if item.name != "z"]
    stepped = acquire(plain, plan([stream()], planes=planes)).published[0].data
    assert np.array_equal(wired, stepped)


@pytest.mark.parametrize(
    "planes, finding",
    [
        ([0.0, 3.0, 6.0], "steps the stage by 2.0 um"),
        ([40.0, 42.0, 44.0, 46.0, 48.0, 50.0, 52.0], "outside the stage's travel"),
    ],
)
def test_a_stack_the_wire_cannot_do_is_refused_before_anything_moves(
    tmp_path: Path, planes: list[float], finding: str
) -> None:
    """The spacing is the wire's, and a sweep has no move that would check the travel."""
    m = compiled(tmp_path)
    counting = CountingMoves(m)
    with pytest.raises(ValueError, match=finding):
        acquire(m, plan([stream()], planes=planes))
    assert counting.moves == []


def test_hooks_between_swept_planes_are_refused(tmp_path: Path) -> None:
    """Nothing can run between the planes of a sweep."""
    m = compiled(tmp_path)
    config = plan([stream()], planes=[0.0, 2.0])
    config.timepoints[0].positions[0].stacks[0].z_hooks = ["anything"]  # type: ignore[list-item]
    counting = CountingMoves(m)
    with pytest.raises(ValueError, match="between the planes"):
        acquire(m, config)
    assert counting.moves == []


def test_capturing_on_its_own_does_not_step_the_stage(tmp_path: Path) -> None:
    """A driven axis only runs through a stack, or a live view would walk off."""
    m = compiled(tmp_path)
    m.detector.activate_detector(1)
    m.detector.capture_image(1)
    m.detector.capture_channels(1)
    assert m.stage_state.z == 0.0
