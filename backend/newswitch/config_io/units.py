"""Unit handling for physical values, based on pint.

Every physical-value field declares the unit newswitch works in (``ms``, ``Hz``, ``um/s``,
...). A value stated in a different but compatible unit is converted; an incompatible or
unknown unit cannot be used and is reported by the caller as a `ConfigWarning`.
Logarithmic units (dB) are not converted at all, only compared by name.
"""

from __future__ import annotations

from functools import lru_cache

import pint

# Units pint cannot scale linearly; they are accepted only when spelled like the target.
LOGARITHMIC_UNITS = {"db"}


@lru_cache(maxsize=1)
def _registry() -> pint.UnitRegistry:
    """Build the unit registry once; constructing it takes a noticeable fraction of a second."""
    return pint.UnitRegistry()


def conversion_factor(source: str, target: str) -> float:
    """Return the factor that turns a number in `source` units into `target` units.

    Args:
        source: Unit as written in the config, e.g. ``"s"`` or ``"mm/s"``.
        target: Unit newswitch expects, e.g. ``"ms"`` or ``"um/s"``.

    Returns:
        The multiplicative factor (1.0 when the units are the same).

    Raises:
        ValueError: The units are unknown, incompatible, or logarithmic and not identical.
    """
    if source.strip().lower() in LOGARITHMIC_UNITS or target.strip().lower() in LOGARITHMIC_UNITS:
        if source.strip().lower() == target.strip().lower():
            return 1.0
        raise ValueError(f"cannot convert logarithmic unit {source!r} to {target!r}")
    try:
        return float(_registry().Quantity(1.0, source).to(target).magnitude)
    except (pint.errors.PintError, AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"cannot convert {source!r} to {target!r}: {exc}") from exc
