"""Anything on the way to a detector can move, and what that does is traced: nothing says it.

A camera on a slide, a tube lens on a mount: the description only gives them a move. Where the image
goes, and whether it is still sharp, comes from placing each where its moves put it and tracing.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from newswitch.instrument import spec
from newswitch.instrument.compiler import compile_instrument, traced_answer
from newswitch.instrument.roles import Roles
from newswitch.simulation.simulator import Simulator

INSTRUMENTS = Path(__file__).parent.parent / "instruments"

#: dual-camera: a 20 mm objective and 200 mm tube lenses, so 10 times; 6.5 um pixels.
MAGNIFICATION = 10.0


def a_move(along: str) -> dict[str, Any]:
    """A move of 10 um steps along `along`, with no actuator behind it."""
    return {"along": along, "initial": "0 um", "step": "10 um", "min": "-5000 um", "max": "5000 um"}


def on_mounts(data: dict[str, Any]) -> None:
    """The green camera on a slide across and along the axis, its tube lens on one across."""
    data["cubes"]["camera_green"]["moves"] = {
        "x": a_move("x"),
        "y": a_move("y"),
        "dz": a_move("axis"),
    }
    data["cubes"]["tube_green"]["moves"] = {"x": a_move("x")}


def described(tmp_path: Path, change: Callable[[dict[str, Any]], Any]) -> spec.Instrument:
    """dual-camera, as changed by `change`."""
    data = yaml.safe_load((INSTRUMENTS / "dual-camera" / spec.DESCRIPTION).read_text())
    data.pop("ui", None)
    data.pop("agent_ui", None)
    change(data)
    (tmp_path / spec.DESCRIPTION).write_text(yaml.safe_dump(data))
    return spec.load(tmp_path)


@pytest.fixture(scope="module")
def instrument(tmp_path_factory: pytest.TempPathFactory) -> spec.Instrument:
    """dual-camera with its green camera and tube lens on mounts."""
    return described(tmp_path_factory.mktemp("on-mounts"), on_mounts)


def test_a_camera_moved_sideways_looks_elsewhere(instrument: spec.Instrument) -> None:
    """By its move, through the magnification; and the table says what tracing says."""
    table = compile_instrument(instrument)
    state = {**instrument.initial_state(), "camera_green.x": 100.0, "camera_green.y": -50.0}
    traced = traced_answer(instrument, "camera_green", state)
    assert np.abs(traced.centre) == pytest.approx((100.0 / MAGNIFICATION, 50.0 / MAGNIFICATION))
    assert table.answer("camera_green", state).centre == pytest.approx(traced.centre)


def test_only_what_is_on_its_way_moves_a_detectors_image(instrument: spec.Instrument) -> None:
    """The red camera has neither the green one nor its tube lens on its way."""
    state = {**instrument.initial_state(), "camera_green.x": 100.0, "tube_green.x": 300.0}
    assert traced_answer(instrument, "camera_red", state).centre == pytest.approx((0.0, 0.0))


def test_a_lens_and_a_camera_moved_alike_cancel(instrument: spec.Instrument) -> None:
    """Behind the objective the light is parallel: the image follows the tube lens one for one."""
    table = compile_instrument(instrument)
    start = instrument.initial_state()
    lens_only = table.answer("camera_green", {**start, "tube_green.x": 100.0})
    both = table.answer("camera_green", {**start, "tube_green.x": 100.0, "camera_green.x": 100.0})
    assert abs(lens_only.centre[0]) == pytest.approx(100.0 / MAGNIFICATION)
    assert both.centre == pytest.approx((0.0, 0.0), abs=1e-6)
    traced = traced_answer(
        instrument, "camera_green", {**start, "tube_green.x": 100.0, "camera_green.x": 100.0}
    )
    assert traced.centre == pytest.approx((0.0, 0.0), abs=1e-6)


def test_a_camera_can_refocus_what_the_stage_took_out_of_focus(
    instrument: spec.Instrument,
) -> None:
    """A sample 10 um away is sharp again with the camera 10 um times the magnification squared
    nearer: one move undoes the other, traced and from the table."""
    table = compile_instrument(instrument)
    start = instrument.initial_state()
    away = {**start, "stage.z": 10.0}
    refocused = {**away, "camera_green.dz": -10.0 * MAGNIFICATION**2}
    worse = {**away, "camera_green.dz": 10.0 * MAGNIFICATION**2}
    for find in (
        lambda state: traced_answer(instrument, "camera_green", state),
        lambda state: table.answer("camera_green", state),
    ):
        sharp, blurred = find(start).spot_px, find(away).spot_px
        assert blurred > 3.0 * sharp
        assert find(refocused).spot_px == pytest.approx(sharp, rel=0.05)
        assert find(worse).spot_px > 1.8 * blurred


def test_what_a_move_is_for_is_found(instrument: spec.Instrument) -> None:
    """A camera's slide moves where it looks, as the stage does, so asking for the one refuses."""
    roles = Roles(instrument)
    sideways = {move.name for move in roles.sideways("camera_green", "x")}
    assert sideways == {"stage.x", "camera_green.x", "tube_green.x"}
    assert {move.name for move in roles.sideways("camera_red", "x")} == {"stage.x"}
    with pytest.raises(ValueError, match="Several things"):
        roles.x("camera_green")
    assert "blur" in roles.found["camera_green", "stage"]["camera_green.dz"]


def test_the_rendered_image_moves_with_the_camera(instrument: spec.Instrument) -> None:
    """A camera moved by ten of its pixels shows what the stage, moved to match, would show."""
    simulator = Simulator(instrument)
    start = {**instrument.initial_state(), "laser_488.power": 20.0}
    moved = {**start, "camera_green.x": 65.0}
    centre = simulator._answer("camera_green", moved).centre
    assert abs(centre[0]) == pytest.approx(6.5)
    matched = {**start, "stage.x": centre[0], "stage.y": centre[1]}
    pattern = simulator.simulation_of("stage").pattern

    def beads(state: dict[str, Any]) -> np.ndarray:
        return simulator._slice(
            "camera_green", state, simulator._answer("camera_green", state), pattern
        )

    assert beads(moved).sum() > 0.0
    assert np.allclose(beads(moved), beads(matched))
    assert not np.allclose(beads(moved), beads(start))
