"""Tests for `Bounded`, the numeric parameter that carries its own device limits.

Covers the two accepted spellings (bare scalar and full object), the cross-field
rules that JSON Schema cannot express, the clamp/snap helpers, and the custom JSON
Schema emission that keeps the shorthand valid in the jsonschema layer too.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from newswitch.schemas import Bounded


def test_scalar_shorthand_equals_explicit_value() -> None:
    """A bare number is accepted as shorthand for ``{"value": <number>}``."""
    assert Bounded.model_validate(10.0) == Bounded.model_validate({"value": 10.0})
    assert Bounded.model_validate(10).value == 10.0


def test_bool_is_not_a_number() -> None:
    """``True`` is an int in Python but must not become ``{"value": 1.0}``."""
    with pytest.raises(ValidationError):
        Bounded.model_validate(True)


def test_all_fields_optional() -> None:
    """Every member is optional: limits without a value are a valid capability block."""
    capability = Bounded.model_validate({"min": 0.024, "max": 10000.0})
    assert capability.value is None
    assert Bounded().model_dump(exclude_none=True) == {}


def test_min_above_max_rejected() -> None:
    """An inverted limit pair is a configuration error."""
    with pytest.raises(ValidationError, match="must not exceed max"):
        Bounded(min=10.0, max=1.0)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"value": 0.01, "min": 0.024}, "below min"),
        ({"value": 20000.0, "max": 10000.0}, "above max"),
        ({"value": 10.0005, "min": 0.0, "increment": 0.001}, "not on the"),
    ],
)
def test_value_checked_against_its_own_limits(payload: dict[str, Any], message: str) -> None:
    """`value` is validated against the min/max/increment of the same object.

    Args:
        payload: The `Bounded` document under test.
        message: Fragment expected in the error message.
    """
    with pytest.raises(ValidationError, match=message):
        Bounded.model_validate(payload)


def test_increment_must_be_positive() -> None:
    """A zero or negative step size cannot describe a grid."""
    with pytest.raises(ValidationError):
        Bounded(increment=0.0)


def test_grid_is_anchored_at_min() -> None:
    """Settable values are ``min + n * increment``, not ``n * increment``."""
    assert Bounded(value=0.35, min=0.05, increment=0.1).value == 0.35
    with pytest.raises(ValidationError, match="not on the"):
        Bounded(value=0.3, min=0.05, increment=0.1)


def test_extra_keys_rejected() -> None:
    """A typo such as ``maximum`` must fail loudly instead of being ignored."""
    with pytest.raises(ValidationError):
        Bounded.model_validate({"value": 1.0, "maximum": 10.0})


def test_assignment_is_validated_but_not_rolled_back() -> None:
    """An out-of-range assignment raises — yet the instance keeps the bad value.

    `validate_assignment` sets the field first and only then runs the model-level
    validator, so when `_check_consistency` rejects the new value the object is
    already holding it. Callers must therefore treat a caught `ValidationError`
    as "this object is now unusable", not as "nothing happened". Pinned here so a
    later switch to a rollback-capable design shows up as a failing test.
    """
    exposure = Bounded(value=10.0, min=0.024, max=10000.0)
    with pytest.raises(ValidationError, match="above max"):
        exposure.value = 99999.0
    assert exposure.value == 99999.0


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (1e6, 10000.0),  # clamped to max
        (0.0, 0.024),  # clamped to min
        (10.00047, 10.0),  # snapped down onto the grid
        (10.0006, 10.001),  # snapped up onto the grid
    ],
)
def test_clamp(requested: float, expected: float) -> None:
    """`clamp` limits to [min, max] and snaps onto the increment grid.

    Args:
        requested: The value handed to `clamp`.
        expected: The value the device would actually take.
    """
    exposure = Bounded(value=10.0, min=0.024, max=10000.0, increment=0.001)
    assert exposure.clamp(requested) == pytest.approx(expected)


def test_clamp_never_returns_a_value_above_max() -> None:
    """Snapping up must not push the result past `max`; it steps back down instead."""
    coarse = Bounded(min=0.0, max=8.0, increment=3.0)
    assert coarse.clamp(8.0) == pytest.approx(6.0)
    assert coarse.supports(coarse.clamp(8.0))


def test_supports() -> None:
    """`supports` answers whether a value can be set exactly, without raising."""
    exposure = Bounded(value=10.0, min=0.024, max=10000.0, increment=0.001)
    assert exposure.supports(10.001)
    assert not exposure.supports(10.0005)
    assert not exposure.supports(20000.0)


def test_json_schema_accepts_both_spellings() -> None:
    """The exported schema must emit ``anyOf: [number, object]``.

    Without the `__get_pydantic_json_schema__` override the scalar shorthand would
    pass Pydantic and fail the jsonschema layer, so the two layers would disagree.
    """
    schema = Bounded.model_json_schema()
    assert "anyOf" in schema
    kinds = {branch.get("type") for branch in schema["anyOf"]}
    assert "number" in kinds
    assert "object" in kinds


def test_repr_hides_unset_members() -> None:
    """The repr stays readable by dropping the members that are None."""
    assert repr(Bounded(value=10.0)) == "Bounded(value=10.0)"
