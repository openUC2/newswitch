"""Fluorescence controls built from blok primitives.

What sets a fluorescence microscope apart is its light: a source excites a dye at one
colour, the dye glows at a longer one, and only that glow reaches the camera (through the
dichroic and the emission filter), while every photon of excitation bleaches the sample.
The controls here are about exactly that:

- a channel per light source, named after the dyes its wavelength excites and tinted in
  its colour, with the light path it opens (excitation, sample, emission, camera) and a
  closed shutter while it is off;
- detection as collecting photons: exposure and gain, and the light each frame costs;
- an acquire button that is a shutter over the live image, or, while the light path is
  not calibrated, the call to calibrate it.

Nothing here is a built-in panel: every control is a catalog primitive (``div``,
``span``, Switch, Slider, Button, ``foreach``, ``if``) bound to newswitch's states and
calling its actions (blok language v2), styled with Tailwind classes (compiled at run
time) in the theme's colour roles, and computed with the vocabulary's functions
(``fmt.*``, ``math.*``, ``list.*``, ``val.*``). The channel tiles are generated here, one
per wavelength band, each in its band's spectral roles (``spectrum-<band>``), which is how
a blok picks colours from a value.

The fragments are bare trees; a view wraps them in its ``<Html>`` root.

Used only by ``python -m newswitch.tools.build_design``, which writes the bloks into a
configuration's ``ui``; newswitch itself reads them from there.
"""

from dataclasses import dataclass

from newswitch.config_io import BlokEntry

NAME = "view-fluorescence"


@dataclass(frozen=True)
class Band:
    """A band of excitation wavelengths: the dyes it excites, and their colours."""

    key: str
    below_nm: float | None  # the band ends here; None for the last one
    dyes: str
    excitation: str  # a spectral colour role, e.g. "spectrum-cyan"
    emission: str
    emission_nm: str


BANDS = [
    Band("uv", 430, "DAPI · Hoechst", "spectrum-violet", "spectrum-blue", "~460 nm"),
    Band("blue", 520, "GFP · FITC", "spectrum-cyan", "spectrum-green", "~510 nm"),
    Band("green", 600, "mCherry · RFP", "spectrum-yellow", "spectrum-orange", "~610 nm"),
    Band("red", None, "Cy5 · far red", "spectrum-red", "spectrum-red", "~670 nm"),
]

#: A tile on the dark scene: hairline border, a little glass.
TILE = "relative overflow-hidden rounded-2xl border border-border/60 bg-card/70 p-4 shadow-xl"
#: A small caps label above a value.
EYEBROW = "text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground"


def _path(band: Band, on: bool) -> str:
    """The light path the source opens: excitation, sample, emission, camera."""
    if not on:
        return f"""
            <div className="mt-4 flex items-center gap-1.5 opacity-40 grayscale">
                <span className="size-2.5 rounded-full bg-{band.excitation}" />
                <div className="h-px flex-1 border-t border-dashed border-muted-foreground/30" />
                <span className="rounded-md border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">sample</span>
                <div className="h-px flex-1 border-t border-dashed border-muted-foreground/30" />
                <span className="size-2.5 rounded-sm bg-{band.emission}" />
            </div>"""
    return f"""
            <div className="mt-4 flex items-center gap-1.5">
                <span className="size-2.5 rounded-full bg-{band.excitation} shadow-[0_0_14px_3px] shadow-{band.excitation}/70" />
                <div className="h-0.5 flex-1 animate-pulse rounded-full bg-gradient-to-r from-{band.excitation} to-{band.excitation}/30" />
                <span className="rounded-md border border-{band.excitation}/40 bg-{band.excitation}/10 px-1.5 py-0.5 text-[10px] text-foreground">sample</span>
                <div className="h-0.5 flex-1 animate-pulse rounded-full bg-gradient-to-r from-{band.emission}/30 to-{band.emission}" />
                <span className="size-2.5 rounded-sm bg-{band.emission} shadow-[0_0_14px_3px] shadow-{band.emission}/70" />
                <span className="text-[10px] tabular-nums text-{band.emission}">{band.emission_nm}</span>
            </div>"""


def _channel(band: Band) -> str:
    """The tile of a light source in the band: dyes, wavelength, switch, path, power."""
    accent = band.excitation
    return f"""
<div className="{TILE}">
    <div className={{light.is_active ? "pointer-events-none absolute -right-12 -top-12 size-44 rounded-full bg-{accent}/25 blur-3xl" : "pointer-events-none absolute -right-12 -top-12 size-44 rounded-full bg-{accent}/5 blur-3xl"}} />
    <div className="relative flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
            <span className="text-[10px] font-medium uppercase tracking-[0.2em] text-{accent}">{band.dyes}</span>
            <div className="flex items-baseline gap-1.5">
                <span className="text-4xl font-semibold tracking-tight tabular-nums">{{light.wavelength}}</span>
                <span className="text-sm text-muted-foreground">nm</span>
            </div>
            <span className="text-xs lowercase text-muted-foreground first-letter:uppercase">{{light.kind}} · excitation</span>
        </div>
        <div className="past:pointer-events-none past:opacity-50">
            <if when={{light.is_active}}>
                <Switch checked={{true}} className="data-[state=checked]:bg-{accent}" onChange={{self.turn_off_illumination_channel(channel: light.slot)}} />
            <else>
                <Switch checked={{false}} onChange={{self.turn_on_illumination(channel: light.slot)}} />
            </else>
            </if>
        </div>
    </div>
    <if when={{light.is_active}}>
        <div className="relative">{_path(band, on=True)}
            <div className="mt-5 flex items-end justify-between">
                <span className="{EYEBROW}">Power</span>
                <span className="text-2xl font-semibold tabular-nums text-{accent}">{{fmt.percent(value: math.div(a: light.intensity, b: light.max_intensity))}}</span>
            </div>
            <Slider className="mt-2 past:hidden [&amp;_[data-slot=slider-range]]:bg-{accent} [&amp;_[data-slot=slider-thumb]]:border-{accent}" value={{light.intensity}} min={{light.min_intensity}} max={{light.max_intensity}} onCommit={{self.set_illumination_intensity(intensity: event.value, channel: light.slot)}} />
        </div>
    <else>
        <div className="relative">{_path(band, on=False)}
            <span className="mt-4 block text-xs text-muted-foreground">Shutter closed: the sample is dark and does not bleach.</span>
        </div>
    </else>
    </if>
</div>"""


def _bands(index: int = 0) -> str:
    """The tile of the band the light's wavelength falls in: an ``if`` per band edge."""
    band = BANDS[index]
    if band.below_nm is None:
        return _channel(band)
    return f"""
<if when={{light.wavelength < {band.below_nm:g}}}>{_channel(band)}
<else>{_bands(index + 1)}
</else>
</if>"""


#: The light sources, one channel tile each.
EXCITATION = f"""
<div className="flex flex-col gap-3">
    <foreach items={{self.IlluminationState.illuminations}} let="light" key={{light.slot}}>{_bands()}
    </foreach>
</div>"""

#: The objectives: the one in the light path is lit, a click switches.
OBJECTIVES = f"""
<div className="{TILE} flex flex-col gap-2 past:pointer-events-none">
    <span className="{EYEBROW}">Objective</span>
    <foreach items={{self.ObjectiveState.mounted_lenses}} let="lens" key={{lens.slot}}>
        <if when={{lens.slot == self.ObjectiveState.slot}}>
            <div className="flex items-center gap-3 rounded-xl border border-success/40 bg-success/10 px-3 py-2">
                <span className="size-2 rounded-full bg-success shadow-[0_0_10px_2px] shadow-success/60" />
                <span className="text-sm font-medium">{{lens.name}}</span>
            </div>
        <else>
            <Button variant="ghost" fullWidth={{true}} className="justify-start rounded-xl" onClick={{self.switch_objective(slot: lens.slot)}}>{{lens.name}}</Button>
        </else>
        </if>
    </foreach>
</div>"""

#: The emission filters: the one in the light path is lit, a click switches.
EMISSION = f"""
<div className="{TILE} flex flex-col gap-2 past:pointer-events-none">
    <span className="{EYEBROW}">Emission filter</span>
    <foreach items={{self.FilterBankState.filters}} let="filter" key={{filter.slot}}>
        <if when={{filter.slot == self.FilterBankState.current_slot}}>
            <div className="flex items-center gap-3 rounded-xl border border-success/40 bg-success/10 px-3 py-2">
                <span className="size-2 rounded-full bg-success shadow-[0_0_10px_2px] shadow-success/60" />
                <span className="text-sm font-medium">{{filter.name}}</span>
                <span className="ml-auto text-xs tabular-nums text-muted-foreground">{{filter.center_wavelength}}/{{filter.bandwidth}} nm</span>
            </div>
        <else>
            <Button variant="ghost" fullWidth={{true}} className="justify-start rounded-xl" onClick={{self.switch_filter(slot: filter.slot)}}>{{filter.name}} · {{filter.center_wavelength}}/{{filter.bandwidth}} nm</Button>
        </else>
        </if>
    </foreach>
</div>"""

#: Exposure in milliseconds (the state keeps seconds).
_EXPOSURE_MS = "math.mul(a: camera.current_exposure_time, b: 1000)"
#: The first source, whose power a frame takes.
_FIRST = "list.first(value: self.IlluminationState.illuminations)"
#: The share of the first source's power.
_POWER = (
    f'math.div(a: obj.get(value: {_FIRST}, key: "intensity"), '
    f'b: obj.get(value: {_FIRST}, key: "max_intensity"))'
)

#: The cameras as photon collectors: exposure, gain, and the light a frame costs.
DETECTION = f"""
<div className="flex flex-col gap-3">
    <foreach items={{self.CameraState.detectors}} let="camera" key={{camera.slot}}>
        <div className="{TILE}">
            <div className="flex items-center gap-2">
                <div className="flex flex-col">
                    <span className="{EYEBROW}">Detection</span>
                    <span className="truncate text-sm font-medium">{{camera.name}}</span>
                </div>
                <div className="ml-auto">
                    <if when={{self.CameraState.is_acquiring}}>
                        <div className="flex items-center gap-1.5 rounded-full bg-destructive/15 px-2.5 py-1 text-[11px] font-medium text-destructive">
                            <span className="size-1.5 animate-pulse rounded-full bg-destructive" />
                            <span>Live</span>
                        </div>
                    <else>
                        <div className="flex items-center gap-1.5 rounded-full bg-muted/50 px-2.5 py-1 text-[11px] text-muted-foreground">
                            <span className="size-1.5 rounded-full bg-muted-foreground/30" />
                            <span>Idle</span>
                        </div>
                    </else>
                    </if>
                </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="flex min-w-0 flex-col gap-2 rounded-xl bg-muted/30 p-3">
                    <span className="{EYEBROW}">Exposure</span>
                    <div className="flex items-baseline gap-1">
                        <span className="text-2xl font-semibold tabular-nums">{{fmt.number(value: {_EXPOSURE_MS}, digits: 1)}}</span>
                        <span className="text-xs text-muted-foreground">ms</span>
                    </div>
                    <Slider className="min-w-0 past:hidden" step={{0.1}} value={{{_EXPOSURE_MS}}} min={{math.mul(a: camera.min_exposure_time, b: 1000)}} max={{math.mul(a: camera.max_exposure_time, b: 1000)}} onCommit={{self.update_detector(slot: camera.slot, exposure_time: math.div(a: event.value, b: 1000))}} />
                </div>
                <div className="flex min-w-0 flex-col gap-2 rounded-xl bg-muted/30 p-3">
                    <span className="{EYEBROW}">Gain</span>
                    <div className="flex items-baseline gap-1">
                        <span className="text-2xl font-semibold tabular-nums">{{fmt.number(value: camera.current_gain, digits: 1)}}</span>
                        <span className="text-xs text-muted-foreground">dB</span>
                    </div>
                    <Slider className="min-w-0 past:hidden" step={{0.1}} value={{camera.current_gain}} min={{camera.min_gain}} max={{camera.max_gain}} onCommit={{self.update_detector(slot: camera.slot, gain: event.value)}} />
                </div>
            </div>
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-warning/15 bg-warning/5 px-3 py-2">
                <span className="text-xs text-warning/80">Light per frame</span>
                <span className="ml-auto text-xs font-medium tabular-nums text-warning">{{fmt.number(value: {_EXPOSURE_MS}, digits: 1)}} ms at {{fmt.percent(value: {_POWER})}}</span>
            </div>
            <span className="mt-2 block text-[11px] text-muted-foreground">Longer and brighter collects more photons, and bleaches more.</span>
        </div>
    </foreach>
</div>"""


def _pill(dot: str, text: str, tone: str) -> str:
    return f"""
        <div className="flex items-center gap-1.5 rounded-full border border-border/60 bg-card/70 px-2.5 py-1 text-[11px] {tone} backdrop-blur">
            <span className="size-1.5 rounded-full {dot}" />
            <span>{text}</span>
        </div>"""


def _either(when: str, then: str, otherwise: str) -> str:
    return f"""
    <if when={{{when}}}>{then}
    <else>{otherwise}
    </else>
    </if>"""


#: Whether no light path is calibrated (an image would have no pixel size, no place).
_UNCALIBRATED = "val.is_empty(value: self.CalibrationState.calibrated_light_paths)"

#: At a glance: is the sample lit, is the camera streaming, is the light path calibrated.
READINESS = f"""
<div className="flex flex-wrap gap-1.5">{
    _either(
        'list.contains(value: list.pluck(value: self.IlluminationState.illuminations, key: "is_active"), item: true)',
        _pill("bg-info shadow-[0_0_8px_2px] shadow-info/60", "Lit", "text-info"),
        _pill("bg-muted-foreground/30", "Dark", "text-muted-foreground"),
    )
}{
    _either(
        "self.CameraState.is_acquiring",
        _pill("animate-pulse bg-destructive", "Streaming", "text-destructive"),
        _pill("bg-muted-foreground/30", "Idle", "text-muted-foreground"),
    )
}{
    _either(
        _UNCALIBRATED,
        _pill("bg-warning", "Uncalibrated", "text-warning"),
        _pill("bg-success", "Calibrated", "text-success"),
    )
}
</div>"""

#: Taking an image (a shutter button), or, while no light path is calibrated (an image
#: would have no pixel size and no place on the stage), the call to calibrate it.
ACQUIRE_OR_CALIBRATE = f"""
<if when={{{_UNCALIBRATED}}}>
    <div className="flex items-center gap-3 rounded-2xl border border-warning/30 bg-card/80 p-3 shadow-xl backdrop-blur past:hidden">
        <div className="flex min-w-0 flex-1 flex-col">
            <span className="text-sm font-medium text-warning">Light path not calibrated</span>
            <span className="text-xs text-muted-foreground">Calibrate once: images then get their pixel size and their place on the stage.</span>
        </div>
        <Button icon="wand" size="sm" className="shrink-0 rounded-full bg-warning text-warning-foreground hover:bg-warning/80" onClick={{self.calibrate_light_path()}}>Calibrate</Button>
    </div>
<else>
    <Button icon="camera" size="lg" fullWidth={{true}} className="h-12 rounded-full text-base shadow-xl past:hidden" onClick={{self.capture_image()}}>Acquire</Button>
</else>
</if>"""

#: Starting and stopping the live view.
LIVE_BUTTONS = """
<div className="flex gap-1 rounded-full border border-border/60 bg-card/70 p-1 backdrop-blur past:hidden">
    <Button icon="play" size="sm" variant="ghost" className="rounded-full" onClick={self.start_live_view()}>Live</Button>
    <Button icon="square" size="sm" variant="ghost" className="rounded-full" onClick={self.stop_live_view()}>Stop</Button>
</div>"""


def fluorescence_ui(has_filters: bool, has_objectives: bool = False) -> str:
    """The fluorescence view: the image large, the light path's controls beside it."""
    return f"""
<Html>
<div className="flex h-full w-full gap-4 overflow-hidden bg-gradient-to-br from-info/5 to-transparent p-4">
    <ScrollArea className="h-full w-[380px] shrink-0">
        <div className="flex flex-col gap-3 pb-4 pr-3">{READINESS}{EXCITATION}{OBJECTIVES if has_objectives else ""}{EMISSION if has_filters else ""}{DETECTION}
        </div>
    </ScrollArea>
    <div className="relative min-w-0 flex-1 overflow-hidden rounded-2xl border border-border/60 bg-background shadow-2xl">
        <div className="h-full past:opacity-40">
            <LiveView className="h-full" />
        </div>
        <div className="absolute bottom-5 right-4">{LIVE_BUTTONS}
        </div>
        <div className="absolute bottom-5 left-1/2 w-[min(26rem,80%)] -translate-x-1/2">{ACQUIRE_OR_CALIBRATE}
        </div>
    </div>
</div>
</Html>"""


def blok(has_filters: bool, has_objectives: bool = False) -> BlokEntry:
    """The fluorescence view."""
    return BlokEntry(
        bsx=fluorescence_ui(has_filters, has_objectives),
        description="Fluorescence: excitation, emission and detection, built from blok primitives.",
    )
