"""What a UC2 board moves and lights: everything UC2 knows about a variable is in here."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from arkitekt import Task
from koil import unkoil

from newswitch.drivers.base import Driver, Report, register_driver
from newswitch.instrument.spec import Variable
from newswitch.protocols.uc2 import UC2BusManager


@dataclass(frozen=True)
class StepperConfig:
    """One axis of a board's steppers."""

    axis: str
    steps_per_um: float
    """Nothing can be said about this one: a wrong guess moves the sample somewhere else."""


class Stepper:
    """A move along one axis of the board, at the speed its variable states."""

    def __init__(self, bus: UC2BusManager, config: StepperConfig, speed: float | None) -> None:
        """A stepper on `bus`, moving at `speed` micrometres per second, or the board's own."""
        self.bus = bus
        self.config = config
        self.speed = speed

    def start(self, initial: Any) -> Any:  # noqa: ANN401 - whatever the variable holds
        """Where the board says it is, once its first event comes; until then, what is described."""
        return initial

    def set(self, value: Any, report: Report, task: Task | None = None) -> None:  # noqa: ANN401
        """Move there, and return once it is."""
        type(self).set_together([(self, value, report)], task)

    @classmethod
    def set_together(
        cls, targets: Iterable[tuple[Driver, Any, Report]], task: Task | None = None
    ) -> None:
        """Move all of them at once. Cancelling stops them on the board: it propagates into the bus."""

        async def go() -> None:
            await asyncio.gather(
                *(
                    driver.bus.amove_axis(
                        driver.config.axis, value, is_absolute=True, speed=driver.speed
                    )
                    for driver, value, _ in targets
                )
            )

        targets = list(targets)
        unkoil(go)
        for _, value, report in targets:
            report(value)


class _OneAtATime:
    """What has nothing to wait for together with others of its kind."""

    def start(self, initial: Any) -> Any:  # noqa: ANN401 - whatever the variable holds
        """It starts where it was described to."""
        return initial

    @classmethod
    def set_together(
        cls, targets: Iterable[tuple[Driver, Any, Report]], task: Task | None = None
    ) -> None:
        """One after the other."""
        for driver, value, report in targets:
            driver.set(value, report, task)


@dataclass(frozen=True)
class LaserConfig:
    """A channel of a board's lasers."""

    channel: int
    pwm_max: int = 1023


class Laser(_OneAtATime):
    """A source's power, as a share of the board's full scale."""

    def __init__(self, bus: UC2BusManager, config: LaserConfig, maximum: float) -> None:
        """A laser on `bus`, whose full scale is `maximum`, in its variable's unit."""
        self.bus = bus
        self.config = config
        self.maximum = maximum

    def start(self, initial: Any) -> Any:  # noqa: ANN401 - whatever the variable holds
        """Nothing turned it on yet, whatever it is described to start from."""
        return 0.0

    def set(self, value: Any, report: Report, task: Task | None = None) -> None:  # noqa: ANN401
        """Set its counts."""
        share = max(0.0, min(1.0, value / self.maximum))
        unkoil(self.bus.aset_laser, self.config.channel, round(share * self.config.pwm_max))
        report(value)


@dataclass(frozen=True)
class WheelConfig:
    """A wheel on one axis of the board."""

    axis: str
    positions: dict[int, float]
    """Where each slot is, along the axis."""


class Wheel(_OneAtATime):
    """A swap by moving an axis to the position of a slot."""

    def __init__(self, bus: UC2BusManager, config: WheelConfig) -> None:
        """A wheel on `bus`."""
        self.bus = bus
        self.config = config

    def set(self, value: Any, report: Report, task: Task | None = None) -> None:  # noqa: ANN401
        """Turn to the slot."""
        unkoil(
            self.bus.amove_axis, self.config.axis, self.config.positions[value], is_absolute=True
        )
        report(value)


class Turret(_OneAtATime):
    """A swap by the board's objective changer."""

    def __init__(self, bus: UC2BusManager) -> None:
        """A turret on `bus`."""
        self.bus = bus

    def set(self, value: Any, report: Report, task: Task | None = None) -> None:  # noqa: ANN401
        """Change to the slot."""
        unkoil(self.bus.aobjective_move, value)
        report(value)


def _bus(context: Mapping[str, Any]) -> UC2BusManager:
    """The board a driver goes through; a third party's driver may need none, these do."""
    if context.get("bus") is None:
        raise TypeError("it needs a board in hardware.boards")
    return context["bus"]


def _stepper(variable: Variable, options: Mapping[str, Any], context: Mapping[str, Any]) -> Driver:
    return Stepper(_bus(context), StepperConfig(**options), variable.speed)


def _laser(variable: Variable, options: Mapping[str, Any], context: Mapping[str, Any]) -> Driver:
    if variable.max is None:
        raise TypeError("a laser's power needs a max: it is what the board's full scale means")
    return Laser(_bus(context), LaserConfig(**options), variable.max)


def _wheel(variable: Variable, options: Mapping[str, Any], context: Mapping[str, Any]) -> Driver:
    config = WheelConfig(**options)
    if sorted(config.positions) != sorted(variable.slots):
        raise TypeError(f"a wheel needs a position for each of the slots {sorted(variable.slots)}")
    return Wheel(_bus(context), config)


def _turret(variable: Variable, options: Mapping[str, Any], context: Mapping[str, Any]) -> Driver:
    # Where each slot is, in steps, is the board's to know: the bus is built with them.
    unknown = set(options) - {"positions"}
    if unknown:
        raise TypeError(f"a turret takes its positions, not {sorted(unknown)}")
    if options and not hasattr(_bus(context).config, "objective_slot_positions_steps"):
        raise TypeError("only a canopen board takes positions, this board's firmware keeps its own")
    return Turret(_bus(context))


register_driver("uc2.stepper", _stepper)
register_driver("uc2.laser", _laser)
register_driver("uc2.wheel", _wheel)
register_driver("uc2.turret", _turret)
