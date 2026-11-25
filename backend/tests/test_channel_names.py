"""Channel names: inferred from the light path a channel takes, by the rules of a file.

The code measures what a path does; `channel_names.yml` says what that is called. So a name follows
the filters, the side the light comes from and the detector, never what is simulated on the sample;
and another file names everything otherwise, without a line of code changing.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from newswitch.instrument import spec
from newswitch.instrument.compiler import compile_instrument
from newswitch.instrument.naming import NAMES, channel_names, naming_from

INSTRUMENTS = Path(__file__).parents[1] / "instruments"


def names(instrument_name: str, naming: Any = None, **state: Any) -> dict[tuple, str]:  # noqa: ANN401
    """Each channel's name, by its source, detector and sample."""
    instrument = spec.load(INSTRUMENTS / instrument_name)
    current = {**instrument.initial_state(), **state}
    found = compile_instrument(instrument).channels(current)
    named = channel_names(instrument, found, current, lambda name, slot: f"{name}={slot}", naming)
    return {(c.source, c.detector, c.sample): name for c, (name, _) in zip(found, named)}


def test_switches_name_each_channel_by_its_path() -> None:
    """GFP through the filter on both cameras, made apart by the camera; white light through the
    section, onto a color camera and onto a mono one."""
    assert names("switch-microscope") == {
        ("laser_488", "cam_color", "stage_a"): "GFP · 488/525 · cam_color",
        ("laser_488", "cam_mono", "stage_a"): "GFP · 488/525 · cam_mono",
        ("white_led", "cam_color", "stage_b"): "Brightfield RGB",
        ("white_led", "cam_mono", "stage_b"): "Brightfield white",
    }


@pytest.mark.parametrize(
    ("instrument", "expected"),
    [
        ("he-microscope", {"Brightfield RGB"}),
        ("light-sheet", {"Light-sheet GFP · 488/525"}),
        ("flim", {"FLIM GFP · 488/525"}),
        ("point-scanner", {"Confocal GFP · 488/525"}),
        ("dual-camera", {"GFP · 488/525", "Brightfield 625"}),
    ],
)
def test_how_the_light_makes_the_image_names_it(instrument: str, expected: set[str]) -> None:
    """From the side, timed, scanned, through a band-pass or straight through: each is said."""
    assert set(names(instrument).values()) == expected


def test_a_long_pass_is_said_as_one() -> None:
    """Only the dichroic between the laser and the camera: what arrives is above its cut."""
    assert set(names("rgb-camera").values()) == {"GFP · 488/>500", "Brightfield RGB"}


def test_a_name_is_of_the_path_not_of_the_sample(tmp_path: Path) -> None:
    """Whatever is simulated on the stage, the channels and their names are the same: the light
    path alone says (`compiler.reach`), as on a real instrument, which does not know what is
    mounted."""
    instrument = spec.load(INSTRUMENTS / "light-sheet")
    data = yaml.safe_load((INSTRUMENTS / "light-sheet" / spec.DESCRIPTION).read_text())
    data["cubes"]["stage"]["element"]["simulation"] = "empty-slide"
    data.pop("ui", None)
    (tmp_path / spec.DESCRIPTION).write_text(yaml.safe_dump(data))
    empty = spec.load(tmp_path / spec.DESCRIPTION)
    state = instrument.initial_state()

    def named(of: spec.Instrument) -> list[str]:
        found = compile_instrument(of).channels(state)
        return [name for name, _ in channel_names(of, found, state, lambda n, s: f"{n}={s}")]

    assert named(empty) == named(instrument) != []


def custom(change: Any) -> Any:  # noqa: ANN401 - a Naming
    """The library's naming, changed by `change`."""
    data = yaml.safe_load(NAMES.read_text())
    change(data)
    return naming_from(data)


def test_another_file_names_everything_otherwise() -> None:
    """GFP is "Green" and fluorescence says so: no code changed."""

    def green(data: dict) -> None:
        for dye in data["dyes"]:
            if dye["name"] == "GFP":
                dye["name"] = "Green"
        for rule in data["rules"]:
            if rule.get("when") == {"emitted": True}:
                rule["name"] = "Fluo {dye} ({excitation})"

    assert names("dual-sample", custom(green))[("laser_488", "cam_a", "stage_a")] == (
        "Fluo Green (488)"
    )


def test_what_fits_no_dye_is_said_otherwise() -> None:
    """Without dyes, a fluorescence channel is what the file says of one that fits none."""

    def none(data: dict) -> None:
        data["dyes"] = []

    assert names("dual-sample", custom(none))[("laser_488", "cam_a", "stage_a")] == (
        "Fluorescence · 488/525"
    )


def test_names_alike_are_made_apart_in_the_order_the_file_says() -> None:
    """By the sample first: the two GFP channels of the switch microscope are on one sample, so
    the sample does not tell them apart, and then the camera does."""

    def sample_first(data: dict) -> None:
        data["apart_by"] = ["sample", "detector"]

    found = names("switch-microscope", custom(sample_first))
    assert found[("laser_488", "cam_mono", "stage_a")] == "GFP · 488/525 · stage_a · cam_mono"
