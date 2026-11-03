"""What a channel is called: inferred from the light path it takes, by rules in a file.

Nothing here knows a dye, a contrast or a word. `path_facts` measures what a channel's light path
does, neutrally: the source's lines, the side its light lands on the sample from, whether it is
scanned, how much of the source's own light the detection path lets through, the band it passes, and
what the detector is. `channel_names.yml` (or any `Naming`) says what those facts are called: its
rules, its dyes, its words. Changing it renames every channel of every instrument.

Only the light path counts, never what is simulated on the sample: a real instrument does not know
what is mounted.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import field
from functools import cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml
from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass

from newswitch.instrument.hardware import STRICT
from newswitch.instrument.predict import Channel
from newswitch.instrument.spec import Fraction, Instrument, Nanometres, Scanner, Sensor, Source
from newswitch.instrument.tracing import transmission

NAMES = Path(__file__).parent / "channel_names.yml"


@dataclass(frozen=True, config=STRICT)
class When:
    """What must hold of a path's facts for a rule to name it: each that is given."""

    emitted: bool | None = None
    side: Literal["epi", "transmitted", "orthogonal"] | None = None
    scanned: bool | None = None
    timed: bool | None = None
    colors: bool | None = None
    emits: Literal["laser", "led", "lamp"] | None = None
    broad: bool | None = None


@dataclass(frozen=True, config=STRICT)
class Rule:
    """A name for the paths of which `when` holds, with the placeholders of `PathFacts.fields`."""

    name: str
    when: When = field(default_factory=When)


@dataclass(frozen=True, config=STRICT)
class Dye:
    """A name for a path whose source has a line in `excitation` and whose band is in `emission`."""

    name: str
    excitation: tuple[Nanometres, Nanometres]
    emission: tuple[Nanometres, Nanometres]


Part = Literal["detector", "sample", "swaps"]


@dataclass(frozen=True, config=STRICT)
class Naming:
    """How channels are named: the whole of `channel_names.yml`."""

    spectrum: tuple[Nanometres, Nanometres]
    broad_above: Nanometres
    broad: str
    blocked_below: Fraction
    rules: tuple[Rule, ...]
    dyes: tuple[Dye, ...]
    dye_otherwise: str
    apart_by: tuple[Part, ...]
    describe: str
    round_to: Nanometres = 1.0  # what a band's numbers are rounded to


_NAMING = TypeAdapter(Naming)


def naming_from(data: Mapping[str, Any]) -> Naming:
    """A `Naming` from what a file of it states; its spectrum as ``{from, to}``."""
    spectrum = data.get("spectrum")
    if isinstance(spectrum, Mapping):
        data = {**data, "spectrum": (spectrum.get("from"), spectrum.get("to"))}
    return _NAMING.validate_python(data)


@cache
def library_naming() -> Naming:
    """The naming every instrument uses: `channel_names.yml`."""
    return naming_from(yaml.safe_load(NAMES.read_text()))


@dataclass(frozen=True)
class PathFacts:
    """What a channel's light path does: measured, never named."""

    source: str
    detector: str
    sample: str
    emits: str
    excitation_nm: tuple[float, ...]
    broad: bool
    side: str | None
    scanned: bool
    source_through: float
    band: tuple[float, float] | None  # where what the detection path passes is above half its most
    open_low: bool  # it passes everything below the spectrum looked at
    open_high: bool  # and above
    colors: bool
    timed: bool


def _spectrum_of(source: Source, grid: np.ndarray) -> np.ndarray:
    spectrum = np.sum(
        [
            np.exp(-0.5 * ((grid - line.center) / (line.width / 2.355)) ** 2)
            for line in source.spectrum
        ],
        axis=0,
    )
    return spectrum / spectrum.sum()


def path_facts(
    instrument: Instrument, channel: Channel, state: Mapping[str, Any], naming: Naming
) -> PathFacts:
    """What `channel`'s light path does, its swaps set as it sets them, the rest as `state`."""
    under = {**state, **channel.swaps}
    grid = np.arange(naming.spectrum[0], naming.spectrum[1] + 1.0, 1.0)
    source = instrument.cubes[channel.source].element_at(under)
    assert isinstance(source, Source)
    lit = instrument.open_routes(instrument.illumination, channel.source, channel.sample, under)
    seen = instrument.open_routes(instrument.detection, channel.sample, channel.detector, under)
    passed = np.zeros(grid.shape)
    for route in seen:
        curve = np.ones(grid.shape)
        for edge in route:
            curve = curve * transmission(
                instrument.cubes[edge.source].element_at(under), edge.via, grid
            )
        passed = np.maximum(passed, curve)
    half = passed.max() / 2.0
    above = np.nonzero(passed >= half)[0] if half > 0.0 else np.array([], dtype=int)
    detector = instrument.cubes[channel.detector].element_at(under)
    return PathFacts(
        source=channel.source,
        detector=channel.detector,
        sample=channel.sample,
        emits=source.emits,
        excitation_nm=tuple(line.center for line in source.spectrum),
        broad=max(line.width for line in source.spectrum) > naming.broad_above,
        side=lit[0][-1].side if lit else None,
        scanned=any(
            isinstance(instrument.cubes[edge.target].element_at(under), Scanner)
            for route in lit
            for edge in route
        ),
        source_through=float((_spectrum_of(source, grid) * passed).sum()),
        band=(float(grid[above[0]]), float(grid[above[-1]])) if above.size else None,
        open_low=bool(above.size) and above[0] == 0,
        open_high=bool(above.size) and above[-1] == grid.size - 1,
        colors=isinstance(detector, Sensor) and bool(detector.colors),
        timed=any(axis.name == "m" for axis in instrument.detector_axes(channel.detector)),
    )


def _holds(when: When, facts: PathFacts, naming: Naming) -> bool:
    found = {
        "emitted": facts.source_through < naming.blocked_below,
        "side": facts.side,
        "scanned": facts.scanned,
        "timed": facts.timed,
        "colors": facts.colors,
        "emits": facts.emits,
        "broad": facts.broad,
    }
    return all(
        wanted is None or found[name] == wanted
        for name, wanted in (
            (name, getattr(when, name))
            for name in When.__dataclass_fields__  # type: ignore[attr-defined]
        )
    )


def _emission_at(facts: PathFacts) -> float | None:
    """Where the band is, as one wavelength: its middle; where it is open on one side, its edge."""
    if facts.band is None or (facts.open_low and facts.open_high):
        return None
    if facts.open_high:
        return facts.band[0]
    if facts.open_low:
        return facts.band[1]
    return (facts.band[0] + facts.band[1]) / 2.0


def _fields(facts: PathFacts, naming: Naming) -> dict[str, str]:
    """What the placeholders of a name stand for."""
    at = _emission_at(facts)

    def nm(value: float) -> str:
        return f"{round(value / naming.round_to) * naming.round_to:.0f}"

    dye = next(
        (
            dye.name
            for dye in naming.dyes
            if at is not None
            and dye.emission[0] <= at <= dye.emission[1]
            and any(dye.excitation[0] <= line <= dye.excitation[1] for line in facts.excitation_nm)
        ),
        naming.dye_otherwise,
    )
    if facts.band is None or (facts.open_low and facts.open_high):
        emission = band = ""
    elif facts.open_high:
        emission = band = f">{nm(facts.band[0])}"
    elif facts.open_low:
        emission = band = f"<{nm(facts.band[1])}"
    else:
        assert at is not None
        emission = nm(at)
        band = f"{nm(facts.band[0])}–{nm(facts.band[1])}"
    return {
        "dye": dye,
        "excitation": naming.broad
        if facts.broad
        else "/".join(f"{line:.0f}" for line in facts.excitation_nm),
        "emission": emission,
        "band": band,
        "band_nm": f"{band} nm" if band else "",
        "excitation_nm": ""
        if facts.broad
        else "/".join(f"{line:.0f}" for line in facts.excitation_nm) + " nm",
        "source": facts.source,
        "detector": facts.detector,
        "sample": facts.sample,
        "emits": facts.emits,
        "side": facts.side or "",
    }


def _tidy(text: str) -> str:
    """A name with what an empty placeholder left behind taken out: a slash or a dot with nothing
    on one side, a pair of brackets with nothing in them, spaces twice."""
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"/(?=\s|$|,|\))|(?<=\s)/|^/", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(\s*·\s*)+$|^(\s*·\s*)+", "", text)
    text = re.sub(r"(\s*·\s*){2,}", " · ", text)
    text = re.sub(r"\s+,", ",", text)
    return text.strip(" ,")


def name_of(facts: PathFacts, naming: Naming) -> str:
    """What the first rule that holds of `facts` calls it."""
    rule = next((rule for rule in naming.rules if _holds(rule.when, facts, naming)), None)
    if rule is None:
        return f"{facts.source} {facts.detector}"
    return _tidy(rule.name.format_map(_fields(facts, naming)))


def description_of(facts: PathFacts, naming: Naming) -> str:
    """The whole of what a path does, as `naming.describe` puts it."""
    return _tidy(naming.describe.format_map(_fields(facts, naming)))


def channel_names(
    instrument: Instrument,
    channels: Sequence[Channel],
    state: Mapping[str, Any],
    swap_label: Callable[[str, Any], str],
    naming: Naming | None = None,
) -> list[tuple[str, str]]:
    """Each channel's name and description; names that would be alike made apart by what
    `naming.apart_by` says, in its order, until they differ."""
    rules = naming or library_naming()
    facts = [path_facts(instrument, channel, state, rules) for channel in channels]
    names = [name_of(found, rules) for found in facts]
    for part in rules.apart_by:
        alike = {name for name in names if names.count(name) > 1}
        if not alike:
            break
        for index, channel in enumerate(channels):
            if names[index] not in alike:
                continue
            extra = (
                " · ".join(swap_label(name, slot) for name, slot in channel.swaps.items())
                if part == "swaps"
                else getattr(channel, part)
            )
            if extra:
                names[index] = f"{names[index]} · {extra}"
    return [(name, description_of(found, rules)) for name, found in zip(names, facts)]
