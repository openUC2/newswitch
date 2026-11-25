"""What a simulated sample does with the light landing on it: sends some back, emits some.

The optics say what reaches the sample and what the way to a detector lets through
(`newswitch.instrument.tracing.transfer`), for any sample; what a sample on the stage does with it
is the simulation's (`Simulation`: what it reflects, lets through, and its fluorophore).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from newswitch.instrument.spec import Fluorophore, Instrument, Simulation
from newswitch.instrument.tracing import Transfer, couple, gaussian, transfer, wavelengths


def emitted(
    fluorophore: Fluorophore | None, absorbed: float | None, on_sample: np.ndarray, grid: np.ndarray
) -> np.ndarray:
    """How many photons a bead emits, in all directions, for the photons on it."""
    if fluorophore is None or absorbed is None:
        return np.zeros(grid.shape)
    excitation = gaussian(grid, fluorophore.excitation, fluorophore.excitation_width)
    emission = gaussian(grid, fluorophore.emission, fluorophore.emission_width)
    emission = emission / emission.sum()
    return (on_sample * excitation).sum() * absorbed * fluorophore.quantum_yield * emission


def coupling(found: Transfer, simulation: Simulation, grid: np.ndarray) -> dict[str, Any]:
    """How many electrons a source makes at a detector, per milliwatt and millisecond, on what
    `simulation` puts on the sample (`couple`)."""
    return couple(
        found,
        grid,
        lambda side: simulation.reflect if side == "epi" else simulation.transmit,
        lambda on_sample: emitted(simulation.fluorophore, simulation.absorbed, on_sample, grid),
    )


def lines(simulations: list[Simulation]) -> list[float]:
    """The wavelengths what `simulations` emit are stated at: the simulator's grid holds them."""
    return [
        wavelength
        for simulation in simulations
        if simulation.fluorophore is not None
        for wavelength in (simulation.fluorophore.excitation, simulation.fluorophore.emission)
    ]


def grid(instrument: Instrument) -> np.ndarray:
    """The spectrum the simulator computes on: the instrument's, with what every simulation
    emits."""
    return wavelengths(
        instrument,
        extra=lines(
            [
                simulation
                for sample in instrument.samples()
                for simulation in instrument.sample_holder(sample).simulations.values()
            ]
        ),
    )


def traced(
    instrument: Instrument,
    detector: str,
    state: Mapping[str, Any],
    simulation: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Each source's coupling at `detector` under `state`, traced, on the sample it sees with
    `simulation` on it (default: what its holder says is)."""
    holder = instrument.sample_holder(instrument.seen_sample(detector, state))
    on = holder.simulations[simulation or holder.simulation]
    spectrum = grid(instrument)
    return {
        source: coupling(found, on, spectrum)
        for source, found in transfer(instrument, detector, state, spectrum).items()
    }
