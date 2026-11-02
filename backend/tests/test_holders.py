"""What a sample is mounted on: holders from a library, their places, and where they really sit."""

import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from newswitch.actions.space import mount_holder
from newswitch.infra.export_schemas import REFERENCE_INSTRUMENT
from newswitch.instrument import spec
from newswitch.instrument.space import holder_to_stage
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.space import Position
from tests.conftest import run_settings
from tests.test_space import bead_misses, lit_away, on_beads, placed_by_metadata

#: Where the reference microscope's plate really sits, beside where its description says.
OFFSET_UM = (180.0, -95.0)


def edited(tmp_path: Path, change: Any, truth: dict[str, Any] | None = None) -> Path:  # noqa: ANN401
    """A copy of the reference microscope, its description changed by `change`."""
    copy = tmp_path / "instrument"
    shutil.copytree(REFERENCE_INSTRUMENT, copy)
    path = copy / spec.DESCRIPTION
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data))
    if truth is not None:
        (copy / "truth.yml").write_text(yaml.safe_dump(truth))
    return copy


def holder_of(data: dict[str, Any]) -> dict[str, Any]:
    """The sample cube's element."""
    return data["cubes"]["stage"]["element"]


def on_the_plate(tmp_path: Path) -> Microscope:
    """The reference microscope with its plate mounted, sitting `OFFSET_UM` beside its mount."""
    truth = {"mount_offset_um": {"x": OFFSET_UM[0], "y": OFFSET_UM[1]}}
    copy = edited(tmp_path, lambda data: None, truth)
    m = build_microscope(run_settings(tmp_path, instrument=copy), spec.load(copy))
    m.space.mount_holder("plate")
    return m


# --- the library


def test_a_plate_has_its_wells_where_the_standard_puts_them() -> None:
    """96 wells, 9 mm apart, A1 14.38 mm right and 11.24 mm down from the corner."""
    instrument = spec.load(REFERENCE_INSTRUMENT)
    plate = instrument.sample_holder().holders["plate"].holder.plate
    assert plate is not None
    wells = plate.wells()
    assert len(wells) == 96
    assert wells["A1"] == pytest.approx((14.38, 11.24))
    assert wells["B3"] == pytest.approx((14.38 + 18.0, 11.24 + 9.0))
    assert wells["H12"] == pytest.approx((14.38 + 99.0, 11.24 + 63.0))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda h: h.update(mounted="dish"), "none of the holders"),
        (lambda h: h.pop("mounted"), "one is mounted"),
        (lambda h: h["holders"]["slide"].update(holder="slide-1x1"), "no 'slide-1x1' in holders"),
    ],
)
def test_what_cannot_be_mounted_is_refused(tmp_path: Path, change: Any, message: str) -> None:  # noqa: ANN401
    """By what is wrong with it."""
    copy = edited(tmp_path, lambda data: change(holder_of(data)))
    with pytest.raises(spec.SpecError, match=message):
        spec.load(copy)


def test_a_plate_without_wells_is_no_plate() -> None:
    """Only a plate has wells, and a plate has them."""
    with pytest.raises(ValueError, match="only a plate"):
        spec.Holder(
            spec="newswitch/holder/v0",
            description="",
            kind="plate",
            extent=spec.Extent(x="10 mm", y="10 mm"),  # type: ignore[arg-type]
        )


# --- mounting


def test_it_starts_on_what_its_description_mounts(microscope: Microscope) -> None:
    """The slide, its middle on the stage's 0, drawn as wide as it is."""
    state = microscope.space_state
    assert (state.holder, state.holders) == ("slide", ["slide", "plate"])
    assert state.shape is not None
    assert (state.shape.width_um, state.shape.height_um) == (75_000.0, 25_000.0)
    middle = microscope.space.transform(Position("stage", 0.0, 0.0), "sample")
    assert middle[:2] == pytest.approx([37_500.0, 12_500.0])


def test_mounting_is_a_new_sample(microscope: Microscope) -> None:
    """Another mounting, its wells drawn, none of the images taken before, the expanse empty."""
    assert microscope.acquisition is not None
    lit_away(microscope)
    (frame,) = microscope.acquisition.acquire(["camera"])
    before = microscope.space_state.mount_id
    mount_holder(microscope.space, microscope.expanse, "plate")
    state = microscope.space_state
    assert state.holder == "plate" and state.mount_id != before
    assert state.shape is not None and len(state.shape.wells) == 96
    assert microscope.expanse_state.current_frames == []
    with pytest.raises(ValueError, match="no route"):
        microscope.space.transform(Position(f"image:{frame.id}", 0.0, 0.0))
    with pytest.raises(ValueError, match="No holder 'dish'"):
        microscope.space.mount_holder("dish")


def test_a_well_is_a_place_to_go(microscope: Microscope) -> None:
    """B3's middle comes under the middle of the image."""
    assert microscope.values is not None
    microscope.space.mount_holder("plate")
    microscope.values.set(microscope.space.targets(Position("well:B3", 0.0, 0.0), "camera"))
    middle = microscope.space.placement("camera") @ np.array([255.5, 255.5, 0.0, 1.0])
    assert middle[:2] == pytest.approx([(14.38 + 18.0) * 1000.0, (11.24 + 9.0) * 1000.0])


# --- where it really is


def test_the_beads_of_a_well_are_where_the_plate_is(tmp_path: Path) -> None:
    """Mounted where it really sits, the beads of B3 are placed on the beads of B3."""
    m = on_the_plate(tmp_path)
    assert m.values is not None and m.detector is not None
    plate = m.values.instrument.sample_holder().holders["plate"]
    m.space.register_mount(np.linalg.inv(holder_to_stage(plate.mount, OFFSET_UM)).tolist())
    lit_away(m)
    m.values.set(m.space.targets(Position("well:B3", 0.0, 0.0), "camera"))
    image = m.detector.capture_image("camera").data
    misses = bead_misses(m, image, placed_by_metadata(m, "camera"))
    assert on_beads(misses, 3.0), misses


def test_a_plate_beside_its_mount_is_not_where_it_is_said_to_be(tmp_path: Path) -> None:
    """Mounted where the description says, every bead is placed the offset away from where it is."""
    m = on_the_plate(tmp_path)
    assert m.values is not None and m.detector is not None
    lit_away(m)
    m.values.set(m.space.targets(Position("well:B3", 0.0, 0.0), "camera"))
    image = m.detector.capture_image("camera").data
    misses = bead_misses(m, image, placed_by_metadata(m, "camera"))
    assert not on_beads(misses, 3.0), misses
