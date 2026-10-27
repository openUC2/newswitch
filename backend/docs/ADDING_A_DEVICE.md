# Adding a device

How the backend layers fit together, and a step-by-step guide to adding a new device type,
using a heating element as the example: switch it on and off, set its target temperature,
and show the measured temperature in the frontend.

> The heater is a **worked example**; it does not exist in the code base. The snippets follow
> the patterns of the existing devices but have not been run — check them against the current
> code when you use them. Library behaviour described here was checked against
> rekuest-next 2.3.1 and the bundled uc2rest.

How the app is wired as a whole, and the locking basics: `DEVELOPER_OVERVIEW.md`.

## Part 1: the layers

| Layer | Where | Job | Camera example |
|---|---|---|---|
| **Protocol** | `newswitch/protocols/` | **The contract:** data models (`@model`), shared state (`@state`), the manager interface (`@context` + `typing.Protocol`). No hardware code. | `protocols/detector.py`: `Detector`, `CameraState`, `DetectorManager` |
| **Manager** | `newswitch/managers/virtual/`, `newswitch/managers/uc2/` | **The implementation:** talks to the hardware or simulates it, keeps the state current, converts units. Implementations are interchangeable. | `VirtualDetectorManager`, `UC2DetectorManager` |
| **Register** | `newswitch/registers/` (one module per device; `routines.py` registers the workflows of `newswitch/routines/`) | **The public API:** thin functions that become actions (an HTTP route plus a generated frontend hook). They get managers and states injected by type, hold locks, and call the manager. Routines are workflows across several managers. | `update_detector`, `start_live_view`, `run_autofocus` |
| **Wiring** | `newswitch/app.py` | The `@startup` hook `provide_managers` builds states and managers (virtual or real); `@background` and `@shutdown` hooks. | `run_detector_loop`, `close_detector` |
| **Transport** (UC2) | `protocols/uc2.py`, `managers/uc2/*_bus.py` | `UC2BusManager`: one interface to the ESP32 firmware, three transports (REST over serial, CANopen, virtual). | — (cameras use uc2_cam_py instead) |

```
Frontend ──HTTP/WS──▶ Register  heater_turn_on, set_heater_temperature, …   (knows only the protocol)
                          │ injected by type annotation
                          ▼
                     Protocol   Heater · HeaterState · HeaterManager
                          ▲ implemented by
            ┌─────────────┴─────────────┐
   VirtualHeaterManager          UC2HeaterManager
                                        │
                                UC2BusManager (rest | can | virtual)
                                        │
                                ESP32 firmware  /heat_act, /heat_get
```

**The core rule:** registered functions and other managers depend **only on the protocol**.
That is what lets `provide_managers` swap the implementation (`use_virtual_microscope`)
without the API changing.

What the three rekuest decorators do:

- `@model`: makes the class a dataclass and registers it as a structured type. It can be an
  action argument or return value and a field of a state; the codegen generates its
  TypeScript type.
- `@state(required_locks=[...])`: makes every field assignment observable. A change becomes
  a JSON patch that is sent to every connected client. Writing requires the named locks to
  be held.
- `@context(locks=[...])`: only metadata. An action, background task or shutdown hook that
  declares a parameter of this type gets the object injected, and an action taking it holds
  the named locks while it runs.

## Part 2: tutorial — a heating element

Reading the temperature needs **no** action: the state is pushed to the frontend as patches.

### Step 1: protocol — `newswitch/protocols/heater.py`

```python
"""
Heater Manager Protocol

Defines the protocol for heating elements (incubator, stage heater, ...) and their state.
"""

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from rekuest_next import model, state
from rekuest_next.agents.context import context

from newswitch.protocols.base import BackgroundManager

#: Guards `HeaterState`; held by every action that takes a HeaterManager or HeaterState.
HEATER_LOCK = "heater"


@model
@dataclass
class Heater:
    """One heating element with its set point and measured temperature."""

    slot: int = 1
    name: str = "Heater"
    is_on: bool = False
    target_temperature_c: float = 37.0
    """Set point in °C."""
    current_temperature_c: Optional[float] = None
    """Last measured temperature in °C; None before the first reading."""
    min_temperature_c: float = 20.0
    max_temperature_c: float = 45.0


@state(required_locks=[HEATER_LOCK])
@dataclass
class HeaterState:
    """Shared state of all heating elements."""

    heaters: list[Heater] = field(default_factory=list)

    def get_heater(self, slot: int) -> Heater:
        """The heater in a slot.

        Raises:
            ValueError: No heater in this slot.
        """
        for heater in self.heaters:
            if heater.slot == slot:
                return heater
        raise ValueError(f"No heater found with slot {slot}")


@context(locks=[HEATER_LOCK])
@runtime_checkable
class HeaterManager(BackgroundManager, Protocol):
    """Protocol for heater managers; `abackground` keeps the temperatures current."""

    state: HeaterState

    def turn_on(self, slot: int = 1) -> Heater:
        """Start heating towards the heater's target temperature."""
        ...

    def turn_off(self, slot: int = 1) -> Heater:
        """Stop heating."""
        ...

    def set_target_temperature(self, temperature_c: float, slot: int = 1) -> Heater:
        """Set the target temperature in °C, clamped to the heater's range."""
        ...
```

Choices made here:

- **The unit is part of the field name** (`_c`), as `exposure_time_ms` is in the device
  configuration. It prevents unit mix-ups between backend and frontend.
- **The `@model` docstring is one line.** It goes into the generated frontend code, and
  Python 3.12 and 3.13 indent multi-line docstrings differently, which makes the generated
  files differ between machines.
- **Only plain field types:** no tuples, no `dict[str, Any]`, no unions other than
  `Optional`. rekuest maps the others to an opaque `MEMORY_STRUCTURE` instead of JSON.
- **Base `BackgroundManager`:** the protocol requires `async def abackground()` for the
  temperature measurement, the same pattern as `UC2BusManager`.
- The `...` bodies are intentional: a protocol only declares the interface. The managers do
  not inherit from it; they match it structurally, which Pylance checks wherever a manager
  is used as a `HeaterManager`.

Then import `HeaterManager`, `HeaterState` and `Heater` in `protocols/__init__.py` and add
them to `__all__`.

### Step 2: virtual manager — `newswitch/managers/virtual/virtual_heater.py`

```python
"""
Virtual Heater Manager

Simulates heating elements: the temperature approaches the target while a heater is on and
the ambient temperature while it is off.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from rekuest_next.state.lock import acquired_locks

from newswitch.protocols.heater import HEATER_LOCK, Heater, HeaterState

#: Simulation step in seconds.
STEP_S = 0.5


@dataclass
class VirtualHeaterConfig:
    """Configuration for the virtual heater manager."""

    heaters: list[Heater] = field(default_factory=lambda: [Heater(slot=1, name="Incubator")])
    ambient_temperature_c: float = 22.0
    time_constant_s: float = 30.0
    """The temperature covers about 63 % of the way to its goal per time constant."""


class VirtualHeaterManager:
    """Simulated heaters; implements the HeaterManager protocol."""

    state: HeaterState

    def __init__(
        self, heater_state: HeaterState, config: Optional[VirtualHeaterConfig] = None
    ) -> None:
        """Publish the configured heaters, starting at ambient temperature.

        Args:
            heater_state: Shared heater state; its heaters are replaced.
            config: Heaters and simulation constants; defaults to one heater.
        """
        self.state = heater_state
        self.config = config or VirtualHeaterConfig()
        ambient = self.config.ambient_temperature_c
        # unrounded simulation values; the state shows them rounded
        self._temperature_c = {heater.slot: ambient for heater in self.config.heaters}
        self.state.heaters = list(self.config.heaters)
        for heater in self.state.heaters:
            heater.current_temperature_c = ambient

    def turn_on(self, slot: int = 1) -> Heater:
        """Start heating (protocol method)."""
        heater = self.state.get_heater(slot)
        heater.is_on = True
        return heater

    def turn_off(self, slot: int = 1) -> Heater:
        """Stop heating (protocol method)."""
        heater = self.state.get_heater(slot)
        heater.is_on = False
        return heater

    def set_target_temperature(self, temperature_c: float, slot: int = 1) -> Heater:
        """Set the clamped target temperature (protocol method)."""
        heater = self.state.get_heater(slot)
        heater.target_temperature_c = max(
            heater.min_temperature_c, min(heater.max_temperature_c, temperature_c)
        )
        return heater

    async def abackground(self) -> None:
        """Advance the simulated temperatures until shutdown (protocol method)."""
        factor = STEP_S / self.config.time_constant_s
        while True:
            await asyncio.sleep(STEP_S)
            # a background task holds no locks: mark the state's lock as held for the writes
            with acquired_locks(HEATER_LOCK):
                for heater in self.state.heaters:
                    goal = (
                        heater.target_temperature_c
                        if heater.is_on
                        else self.config.ambient_temperature_c
                    )
                    temperature = self._temperature_c[heater.slot]
                    temperature += (goal - temperature) * factor
                    self._temperature_c[heater.slot] = temperature
                    heater.current_temperature_c = round(temperature, 1)
```

Why round, and why keep the unrounded value? A patch is only sent when a value changes (the
state's setter compares old and new value), so rounding to 0.1 °C keeps the patch stream
small. The simulation must still continue from the unrounded value: feeding the rounded value
back would stall the temperature about 3 °C short of the target, where one step changes it
by less than 0.05 °C.

Then export the manager in `managers/virtual/__init__.py`.

### Step 3: real hardware over the UC2 bus

The firmware has a PID heating controller, and uc2rest already wraps it:
`client.temperature.set_temperature(active, target, Kp, Ki, Kd, timeout, …)` sends
`/heat_act`, `get_temperature(isBlocking=True)` sends `/heat_get`. There is no channel
parameter, so the firmware drives **one** heating element. The CANopen firmware has no heater
objects (only `cpu_temperature`).

**3a. Bus protocol** — in `protocols/uc2.py`, class `UC2BusManager`:

```python
    # -- heater ----------------------------------------------------------------------

    async def aheater_set(self, active: bool, target_c: float) -> None:
        """Switch the firmware's heating controller on or off at a set point in °C."""
        ...

    async def aheater_temperature(self) -> Optional[float]:
        """Read the heater's temperature sensor in °C; None when no reading came."""
        ...
```

**3b. All three transports** must implement it; otherwise Pylance reports an error at
`uc2_bus: UC2BusManager = …` in `app.py`.

```python
# rest_bus.py  (AsyncUC2Client.call() runs a blocking uc2rest call off the event loop)
    async def aheater_set(self, active: bool, target_c: float) -> None:
        """Switch the firmware's PID heating controller (``/heat_act``)."""
        client = await self._require_client()
        await client.call(
            client.sync.temperature.set_temperature, active=int(active), target=target_c
        )

    async def aheater_temperature(self) -> Optional[float]:
        """Read the temperature sensor (``/heat_get``)."""
        client = await self._require_client()
        value = await client.call(client.sync.temperature.get_temperature, isBlocking=True)
        return None if value <= -273.0 else float(value)  # uc2rest: -273.15 = no answer

# virtual_bus.py  (in __init__: self._heater_active = False; self._heater_target_c = 37.0)
    async def aheater_set(self, active: bool, target_c: float) -> None:
        """Store the simulated heater switch and set point."""
        self._heater_active = active
        self._heater_target_c = target_c

    async def aheater_temperature(self) -> Optional[float]:
        """Report the set point while heating, room temperature otherwise."""
        return self._heater_target_c if self._heater_active else 22.0

# canopen_bus.py
    async def aheater_set(self, active: bool, target_c: float) -> None:
        """Not available: the CANopen firmware has no heater objects."""
        raise NotImplementedError("the CANopen firmware has no heater objects")

    async def aheater_temperature(self) -> Optional[float]:
        """Not available: the CANopen firmware has no heater objects."""
        raise NotImplementedError("the CANopen firmware has no heater objects")
```

**3c. Hardware manager** — `newswitch/managers/uc2/heater_manager.py`:

```python
"""UC2 heater manager: HeaterManager protocol over the UC2 bus (firmware PID controller)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from koil import unkoil
from rekuest_next.state.lock import acquired_locks

from newswitch.protocols.heater import HEATER_LOCK, Heater, HeaterState
from newswitch.protocols.uc2 import UC2BusManager

logger = logging.getLogger(__name__)

#: The firmware drives one heater; it is published in this slot.
FIRMWARE_SLOT = 1


@dataclass
class UC2HeaterConfig:
    """Configuration for the UC2 heater manager."""

    heaters: list[Heater] = field(default_factory=lambda: [Heater(slot=FIRMWARE_SLOT)])
    poll_interval_s: float = 2.0


class UC2HeaterManager:
    """Heater driven by the UC2 firmware's PID controller; implements HeaterManager."""

    state: HeaterState

    def __init__(
        self,
        heater_state: HeaterState,
        bus: UC2BusManager,
        config: Optional[UC2HeaterConfig] = None,
    ) -> None:
        """Publish the configured heater; nothing is sent until it is switched on."""
        self.state = heater_state
        self.bus = bus
        self.config = config or UC2HeaterConfig()
        self.state.heaters = list(self.config.heaters)

    def _heater(self, slot: int) -> Heater:
        """The heater in a slot.

        Raises:
            ValueError: Not the firmware's slot, or no heater configured there.
        """
        if slot != FIRMWARE_SLOT:
            raise ValueError(f"the UC2 firmware drives one heater (slot {FIRMWARE_SLOT})")
        return self.state.get_heater(slot)

    def turn_on(self, slot: int = 1) -> Heater:
        """Start the firmware controller at the target temperature (protocol method)."""
        heater = self._heater(slot)
        unkoil(self.bus.aheater_set, True, heater.target_temperature_c)
        heater.is_on = True  # hardware first, then the state: it shows what was accepted
        return heater

    def turn_off(self, slot: int = 1) -> Heater:
        """Stop the firmware controller (protocol method)."""
        heater = self._heater(slot)
        unkoil(self.bus.aheater_set, False, heater.target_temperature_c)
        heater.is_on = False
        return heater

    def set_target_temperature(self, temperature_c: float, slot: int = 1) -> Heater:
        """Set the clamped target; sent at once while heating (protocol method)."""
        heater = self._heater(slot)
        target = max(heater.min_temperature_c, min(heater.max_temperature_c, temperature_c))
        if heater.is_on:  # the firmware takes the set point together with the switch
            unkoil(self.bus.aheater_set, True, target)
        heater.target_temperature_c = target
        return heater

    async def abackground(self) -> None:
        """Read the temperature periodically until shutdown (protocol method)."""
        while True:
            try:
                value = await self.bus.aheater_temperature()
            except NotImplementedError as exc:
                logger.warning("heater: %s - no temperature readings", exc)
                return
            except Exception as exc:  # bus not connected yet, or reconnecting
                logger.debug("heater: no temperature reading (%s)", exc)
                value = None
            if value is not None:
                with acquired_locks(HEATER_LOCK):
                    self._heater(FIRMWARE_SLOT).current_temperature_c = round(value, 1)
            await asyncio.sleep(self.config.poll_interval_s)
```

The same pattern as `managers/uc2/illumination_manager.py`: the methods the actions call are
synchronous and reach the asynchronous bus through `unkoil`; the background loop is
`async` and awaits the bus directly.

### Step 4: registers — `newswitch/registers/heater.py`

```python
"""Registered functions for heating elements. Importing this module registers them."""

from rekuest_next.register import register

from newswitch.protocols.heater import Heater, HeaterManager


@register
def heater_turn_on(heater: HeaterManager, slot: int = 1) -> Heater:
    """Start heating towards the target temperature.

    Args:
        slot: Heater slot number

    Returns:
        The heater.
    """
    return heater.turn_on(slot)


@register
def heater_turn_off(heater: HeaterManager, slot: int = 1) -> Heater:
    """Stop heating.

    Args:
        slot: Heater slot number

    Returns:
        The heater.
    """
    return heater.turn_off(slot)


@register
def set_heater_temperature(heater: HeaterManager, temperature_c: float, slot: int = 1) -> Heater:
    """Set the target temperature; it is clamped to the heater's range.

    Args:
        temperature_c: Target temperature in °C
        slot: Heater slot number

    Returns:
        The heater.
    """
    return heater.set_target_temperature(temperature_c, slot)
```

What happens automatically:

- `heater: HeaterManager` is a context: it is injected, it does **not** appear as an
  argument, and it brings the lock `heater` (rekuest's `auto_locks`; an explicit
  `@register(locks=[...])` turns that off).
- The function name becomes the route `POST /heater_turn_on` and the frontend hook
  `useHeaterTurnOn`. It must be unique in the whole registry.
- The `Args:` lines become the argument descriptions in the generated frontend schema.
- The returned `Heater` is the result the frontend's `call` resolves with.

Then add `heater` to the module list in `registers/__init__.py`; `app.py` imports that
package for its registration side effects, so nothing else is needed for the actions.

### Step 5: wiring — `newswitch/app.py`

```python
# imports
from newswitch.protocols.heater import HeaterManager, HeaterState
from newswitch.managers.virtual.virtual_heater import VirtualHeaterManager
from newswitch.managers.uc2.heater_manager import UC2HeaterManager
```

In `provide_managers`, **three** places change:

```python
async def provide_managers(app_context: ImswitchConfig) -> Tuple[
    ...,
    AutofocusState,
    HeaterManager,   # (1) annotation: the TYPE makes it the context "heater_manager"
    HeaterState,     #     and the state "HeaterState"
]:
    ...
    # (2) after uc2_bus has been created
    heater_state = HeaterState()
    if config.use_virtual_microscope:
        heater: HeaterManager = VirtualHeaterManager(heater_state=heater_state)
    else:
        heater = UC2HeaterManager(heater_state=heater_state, bus=uc2_bus)
    ...
    return (
        ...,
        autofocus_state,
        heater,          # (3) same position as in the annotation
        heater_state,
    )
```

Plus the background task:

```python
@background
async def run_heater(heater: HeaterManager) -> None:
    """Keep the heater temperatures current until shutdown."""
    await heater.abackground()
```

### Step 6 (optional): device configuration

Without this step everything runs with the managers' built-in defaults. With it, the heater
is described in `configs/newswitch-config.yaml`:

1. In `config_io/devices.py`, add the class and **register** it: in the `Device` union, in
   `DEVICE_TYPES["heater"]`, in the table of the module docstring, as a `heaters` property
   on `NewswitchConfig` (like `lightsources`), and as an export in `config_io/__init__.py`.
   ```python
   @dataclass(kw_only=True, config=OPEN)
   class HeaterConfig(DeviceBase):
       """Heating element (incubator, stage heater, ...)."""

       type: Literal["heater"] = "heater"
       target_temperature_c: float = Field(default=37.0, description="Set point in °C at startup")
       min_temperature_c: float = Field(default=20.0, description="Lowest set point in °C")
       max_temperature_c: float = Field(default=45.0, description="Highest set point in °C")
   ```
2. In `config_io/adapters.py`, add `heaters(config) -> list[Heater] | None`; the slot is the
   position among the heaters in the file, as in `illuminations`.
3. In `provide_managers`, call `adapters.heaters(devices)` and pass the result as
   `VirtualHeaterConfig(heaters=…)` or `UC2HeaterConfig(heaters=…)`.
4. Regenerate the schema: `uv run python -m newswitch.config_io --export-schema`
   (`tests/config_io/test_schema_drift.py` checks it).
5. Add the entry to the YAML file (snake_case keys; vendor names only in `manufacturer`,
   never in code). If the hardware assignment is needed, also add an entry with `type`/`id`
   to the controller's `mapping`, as for the lasers.
   ```yaml
     incubator-heater:
       type: heater
       name: Incubator
       max_temperature_c: 42
   ```
6. Optionally write the target temperature back on shutdown in
   `adapters.sync_runtime_state`, as exposure and gain are.

### Step 7: tests — `tests/test_heater.py`

```python
"""Tests for the heater: virtual manager and the registered actions."""

import pytest
from fastapi import FastAPI
from rekuest_next.contrib.fastapi import AsyncAgentTestClient
from rekuest_next.state.lock import acquired_locks

from newswitch.managers.virtual.virtual_heater import VirtualHeaterManager
from newswitch.protocols.heater import HEATER_LOCK, HeaterState
from tests.conftest import collect_until_completed


def test_target_is_clamped() -> None:
    """A target outside the heater's range is clamped to it."""
    with acquired_locks(HEATER_LOCK):  # outside an action nobody holds the lock
        manager = VirtualHeaterManager(heater_state=HeaterState())
        heater = manager.set_target_temperature(80.0)
    assert heater.target_temperature_c == heater.max_temperature_c


@pytest.mark.asyncio
async def test_heater_actions(virtual_microscope_app: FastAPI) -> None:
    """Switching on, setting the temperature and switching off complete."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        for action, args in (
            ("heater_turn_on", {"slot": 1}),
            ("set_heater_temperature", {"temperature_c": 30.0, "slot": 1}),
            ("heater_turn_off", {"slot": 1}),
        ):
            result = await client.assign(action, args)
            events = await collect_until_completed(client, result.task_id)
            assert events[-1].event_type == "COMPLETED", f"{action} failed: {events[-1]}"
```

The fixture `virtual_microscope_app` starts with `config_file=None`, so the virtual manager
must work without a configuration — it does, with its defaults.

### Step 8: checks and codegen

1. `just check`: fmt, lint, types, tests. ruff requires type annotations and docstrings
   everywhere.
2. Start the backend, then the frontend (`just dev` does both, in that order). The generator
   creates `HeaterState.ts` (`useHeaterState`), `heaterTurnOn.ts`, `setHeaterTemperature.ts`,
   … and the lock `heater`. If the backend is not reachable it silently falls back to the
   committed files.
3. `just drift-check`. The generated files (`frontend/src/apps/**`, `frontend/blok.json`) are
   committed along with the change.
4. In the frontend, `useHeaterState().data?.heaters[0].current_temperature_c` reads the
   temperature and `useHeaterTurnOn().assign({ slot: 1 })` switches the heater on.

## Pitfalls

1. **The type is the identity.** Contexts and states are matched by the **type annotation**
   of `provide_managers`' return tuple. The annotation and the `return` must have the same
   order.
2. **Who holds the lock when the state is written:**

   | Where | Lock |
   |---|---|
   | action | automatic (the locks of its context and state parameters) |
   | `@startup` | every lock |
   | `@background`, `@shutdown` | **none** — use `with acquired_locks(HEATER_LOCK)` |

   `acquired_locks` is only a **marker** (a ContextVar), not a mutex: it does not serialise
   a background task against an action. It also **replaces** the set of held locks inside
   the block instead of adding to it.
3. **Hardware first, then the state**, so the state shows only what the hardware accepted.
4. **Round sensor values**, or every reading sends a patch.
5. **Switching off on shutdown does not reach the hardware.** On teardown rekuest first
   cancels the background tasks — including `run_uc2_bus`, which closes the REST bus's
   client — and only then runs the shutdown hooks (`BaseAgent.atear_down` in
   `rekuest_next/agents/base.py`). A "heater off" in a shutdown hook therefore waits for a
   bus that is gone. A watchdog is more robust: set a short `timeout` in `/heat_act`
   (uc2rest default 600000000; the unit is probably ms — check the firmware) and renew the
   switch-on command periodically from the background loop. If newswitch dies, the firmware
   then stops heating on its own.
6. **Keep the docs current:** `DEVELOPER_OVERVIEW.md` and `.claude/STATUS.md`.
