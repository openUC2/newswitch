"""Tests for `PhysVal`, its field validators, `Trigger` and unit conversion."""

from __future__ import annotations

import math

import pytest
from pydantic import TypeAdapter, ValidationError

from newswitch.config_io import ConfigWarning, PhysVal, Trigger
from newswitch.config_io.units import conversion_factor
from newswitch.config_io.values import EPS, in_unit, non_negative, positive

PHYS = TypeAdapter(PhysVal)


def test_scalar_shorthand() -> None:
    """A bare number means ``{value: number}``."""
    assert PHYS.validate_python(10) == PhysVal(value=10.0)


def test_defaults() -> None:
    """Unstated members take the documented defaults."""
    phys = PHYS.validate_python({})
    assert phys.value is None
    assert phys.min == -math.inf and phys.max == math.inf
    assert phys.inc == EPS and phys.unit == ""
    assert phys.preset_vals is None and phys.selected_index is None


@pytest.mark.parametrize(
    "data",
    [
        {"min": 5, "max": 1},
        {"value": 0, "min": 1},
        {"value": 11, "max": 10},
        {"inc": 0},
        {"value": 1, "increment": 0.1},  # old key name is rejected
        {"preset_vals": {"short": 1.0}},  # the mapping is value -> name, not name -> value
    ],
)
def test_invalid(data: dict) -> None:
    """Inconsistent limits and unknown keys are errors."""
    with pytest.raises(ValidationError):
        PHYS.validate_python(data)


@pytest.mark.parametrize(
    ("presets", "expected"),
    [
        ([1, 10], [1.0, 10.0]),
        ({1: "short", 10: "long"}, [1.0, 10.0]),
        ([], []),
        (None, []),
    ],
)
def test_preset_forms(presets: object, expected: list[float]) -> None:
    """Presets are a list, a mapping value -> name or null; preset_values() flattens them."""
    phys = PHYS.validate_python({"preset_vals": presets})
    assert phys.preset_vals == presets
    assert phys.preset_values() == expected


@pytest.mark.parametrize("presets", [[1, 10], {1: "short", 10: "long"}])
def test_selected_index_within_presets(presets: object) -> None:
    """selected_index is a 0-based index into the presets, also for named ones."""
    assert PHYS.validate_python({"preset_vals": presets, "selected_index": 1}).selected_index == 1
    with pytest.raises(ValidationError, match="out of range"):
        PHYS.validate_python({"preset_vals": presets, "selected_index": 2})
    with pytest.raises(ValidationError):
        PHYS.validate_python({"preset_vals": presets, "selected_index": -1})


@pytest.mark.parametrize("presets", [None, [], {}])
def test_selected_index_needs_presets(presets: object) -> None:
    """Without presets selected_index must stay null."""
    assert PHYS.validate_python({"preset_vals": presets}).selected_index is None
    with pytest.raises(ValidationError, match="no preset_vals"):
        PHYS.validate_python({"preset_vals": presets, "selected_index": 0})


def test_clamp_snaps_to_grid() -> None:
    """clamp() limits to [min, max] and snaps onto the increment grid."""
    phys = PhysVal(min=0.0, max=1.0, inc=0.25)
    assert phys.clamp(0.3) == 0.25
    assert phys.clamp(7.0) == 1.0
    assert phys.clamp(-3.0) == 0.0
    assert PhysVal().clamp(3.3) == 3.3


def test_in_unit_fills_empty_unit() -> None:
    """An empty unit is taken as the field's unit."""
    assert in_unit("ms")(PhysVal(value=1.0)) == PhysVal(value=1.0, unit="ms")


def test_in_unit_converts_all_numbers() -> None:
    """A compatible unit converts value, limits, increment and presets."""
    converted = in_unit("ms")(
        PhysVal(value=0.5, min=0.001, max=2.0, inc=0.001, unit="s", preset_vals=[0.1])
    )
    assert converted is not None
    assert converted.unit == "ms"
    assert converted.value == pytest.approx(500.0)
    assert converted.min == pytest.approx(1.0)
    assert converted.max == pytest.approx(2000.0)
    assert converted.inc == pytest.approx(1.0)
    assert converted.preset_vals == pytest.approx([100.0])


def test_in_unit_converts_named_presets() -> None:
    """Named presets are converted too; names, order and selected_index are kept."""
    converted = in_unit("ms")(
        PhysVal(unit="s", preset_vals={0.1: "short", 2.0: "long"}, selected_index=1)
    )
    assert converted is not None
    assert isinstance(converted.preset_vals, dict)
    assert list(converted.preset_vals) == pytest.approx([100.0, 2000.0])
    assert list(converted.preset_vals.values()) == ["short", "long"]
    assert converted.selected_index == 1


def test_in_unit_keeps_infinite_limits() -> None:
    """Default limits stay infinite and the default increment stays eps."""
    converted = in_unit("um/s")(PhysVal(value=1.0, unit="mm/s"))
    assert converted is not None
    assert converted.min == -math.inf and converted.max == math.inf and converted.inc == EPS


@pytest.mark.parametrize(
    ("unit", "target"), [("Hz", "ms"), ("parsec/fortnight", "ms"), ("Hz", "dB")]
)
def test_in_unit_drops_unconvertible(unit: str, target: str) -> None:
    """An unusable unit warns and drops the value."""
    with pytest.warns(ConfigWarning):
        assert in_unit(target)(PhysVal(value=1.0, unit=unit)) is None


def test_decibel_is_compared_not_converted() -> None:
    """dB passes when spelled like the target."""
    assert conversion_factor("dB", "dB") == 1.0
    with pytest.raises(ValueError):
        conversion_factor("B", "dB")


def test_sign_validators() -> None:
    """positive/non_negative check only a set value."""
    assert positive(None) is None
    assert positive(PhysVal()) == PhysVal()
    assert non_negative(PhysVal(value=0.0)) == PhysVal(value=0.0)
    with pytest.raises(ValueError):
        positive(PhysVal(value=0.0))
    with pytest.raises(ValueError):
        non_negative(PhysVal(value=-1.0))


def test_trigger() -> None:
    """Hardware triggers take edge/level; software triggers must not."""
    trigger = TypeAdapter(Trigger).validate_python(
        {"type": "hardware", "edge": "falling", "level": 1.5}
    )
    assert trigger.level == 1.5
    with pytest.raises(ValidationError):
        TypeAdapter(Trigger).validate_python({"type": "software", "edge": "rising"})
    with pytest.raises(ValidationError):
        TypeAdapter(Trigger).validate_python({"type": "hardware", "level": "high"})
