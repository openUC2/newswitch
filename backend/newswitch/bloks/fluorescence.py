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
calling its actions, styled with Tailwind classes (compiled at run time) and computed
with the util functions (``compare.*``, ``str.concat``, ``fmt.*``, ``math.*``,
``list.*``). The channel tiles are generated here, one per wavelength band, which is how a
blok picks colours from a value.

The fragments use fixed node ids for their ``if`` branches: each may appear once per blok.

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
    excitation: str  # Tailwind colour, e.g. "sky-400"
    emission: str
    emission_nm: str


BANDS = [
    Band("uv", 430, "DAPI · Hoechst", "violet-400", "blue-400", "~460 nm"),
    Band("blue", 520, "GFP · FITC", "sky-400", "emerald-400", "~510 nm"),
    Band("green", 600, "mCherry · RFP", "lime-300", "rose-400", "~610 nm"),
    Band("red", None, "Cy5 · far red", "red-500", "red-300", "~670 nm"),
]

#: A tile on the dark scene: hairline border, a little glass.
TILE = "relative overflow-hidden rounded-2xl border border-white/10 bg-zinc-950/70 p-4 shadow-xl"
#: A small caps label above a value.
EYEBROW = "text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground"


def _path(band: Band, on: bool) -> str:
    """The light path the source opens: excitation, sample, emission, camera."""
    if not on:
        return f"""
            <div className="mt-4 flex items-center gap-1.5 opacity-40 grayscale">
                <span className="size-2.5 rounded-full bg-{band.excitation}" />
                <div className="h-px flex-1 border-t border-dashed border-white/30" />
                <span text="sample" className="rounded-md border border-white/15 px-1.5 py-0.5 text-[10px] text-muted-foreground" />
                <div className="h-px flex-1 border-t border-dashed border-white/30" />
                <span className="size-2.5 rounded-sm bg-{band.emission}" />
            </div>"""
    return f"""
            <div className="mt-4 flex items-center gap-1.5">
                <span className="size-2.5 rounded-full bg-{band.excitation} shadow-[0_0_14px_3px] shadow-{band.excitation}/70" />
                <div className="h-0.5 flex-1 animate-pulse rounded-full bg-gradient-to-r from-{band.excitation} to-{band.excitation}/30" />
                <span text="sample" className="rounded-md border border-{band.excitation}/40 bg-{band.excitation}/10 px-1.5 py-0.5 text-[10px] text-foreground" />
                <div className="h-0.5 flex-1 animate-pulse rounded-full bg-gradient-to-r from-{band.emission}/30 to-{band.emission}" />
                <span className="size-2.5 rounded-sm bg-{band.emission} shadow-[0_0_14px_3px] shadow-{band.emission}/70" />
                <span text="{band.emission_nm}" className="text-[10px] tabular-nums text-{band.emission}" />
            </div>"""


def _channel(band: Band) -> str:
    """The tile of a light source in the band: dyes, wavelength, switch, path, power."""
    k = band.key
    accent = band.excitation
    return f"""
<div id="channel-{k}" className="{TILE}">
    <if when="@light.is_active" then="glow-{k}" else="no-glow-{k}">
        <div id="glow-{k}" className="pointer-events-none absolute -right-12 -top-12 size-44 rounded-full bg-{accent}/25 blur-3xl" />
        <div id="no-glow-{k}" className="pointer-events-none absolute -right-12 -top-12 size-44 rounded-full bg-{accent}/5 blur-3xl" />
    </if>
    <div className="relative flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
            <span text="{band.dyes}" className="text-[10px] font-medium uppercase tracking-[0.2em] text-{accent}" />
            <div className="flex items-baseline gap-1.5">
                <span text="@light.wavelength" className="text-4xl font-semibold tracking-tight tabular-nums" />
                <span text="nm" className="text-sm text-muted-foreground" />
            </div>
            <span text="@utils.str.concat(values=[light.kind, ' · excitation'])" className="text-xs lowercase text-muted-foreground first-letter:uppercase" />
        </div>
        <div className="past:pointer-events-none past:opacity-50">
            <if when="@light.is_active" then="on-{k}" else="off-{k}">
                <Switch id="on-{k}" checked="true" className="data-[state=checked]:bg-{accent}" onChange="@self.turn_off_illumination_channel(light.slot)" />
                <Switch id="off-{k}" checked="false" onChange="@self.turn_on_illumination(channel=light.slot)" />
            </if>
        </div>
    </div>
    <if when="@light.is_active" then="lit-{k}" else="dark-{k}">
        <div id="lit-{k}" className="relative">{_path(band, on=True)}
            <div className="mt-5 flex items-end justify-between">
                <span text="Power" className="{EYEBROW}" />
                <span text="@utils.fmt.percent(value=utils.math.divide(a=light.intensity, b=light.max_intensity))" className="text-2xl font-semibold tabular-nums text-{accent}" />
            </div>
            <Slider className="mt-2 past:hidden [&amp;_[data-slot=slider-range]]:bg-{accent} [&amp;_[data-slot=slider-thumb]]:border-{accent}" value="@light.intensity" min="@light.min_intensity" max="@light.max_intensity" onCommit="@self.set_illumination_intensity(event, channel=light.slot)" />
        </div>
        <div id="dark-{k}" className="relative">{_path(band, on=False)}
            <span text="Shutter closed: the sample is dark and does not bleach." className="mt-4 block text-xs text-muted-foreground" />
        </div>
    </if>
</div>"""


def _bands(index: int = 0) -> str:
    """The tile of the band the light's wavelength falls in: an ``if`` per band edge."""
    band = BANDS[index]
    if band.below_nm is None:
        return _channel(band)
    rest = BANDS[index + 1]
    rest_id = f"channel-{rest.key}" if rest.below_nm is None else f"from-{rest.key}"
    rest_tree = _bands(index + 1)
    if rest.below_nm is not None:
        rest_tree = f'<div id="from-{rest.key}" className="contents">{rest_tree}</div>'
    return f"""
<if when="@utils.compare.lt(a=light.wavelength, b={band.below_nm})" then="channel-{band.key}" else="{rest_id}">{_channel(band)}{rest_tree}
</if>"""


#: The light sources, one channel tile each.
EXCITATION = f"""
<div className="flex flex-col gap-3">
    <foreach items="@self.IlluminationState.illuminations" let="#light">{_bands()}
    </foreach>
</div>"""

#: The emission filters: the one in the light path is lit, a click switches.
EMISSION = f"""
<div className="{TILE} flex flex-col gap-2 past:pointer-events-none">
    <span text="Emission filter" className="{EYEBROW}" />
    <foreach items="@self.FilterBankState.filters" let="#filter">
        <if when="@utils.compare.eq(a=filter.slot, b=self.FilterBankState.current_slot)" then="filter-in" else="filter-out">
            <div id="filter-in" className="flex items-center gap-3 rounded-xl border border-emerald-400/40 bg-emerald-400/10 px-3 py-2">
                <span className="size-2 rounded-full bg-emerald-400 shadow-[0_0_10px_2px] shadow-emerald-400/60" />
                <span text="@filter.name" className="text-sm font-medium" />
                <span text="@utils.str.concat(values=[filter.center_wavelength, '/', filter.bandwidth, ' nm'])" className="ml-auto text-xs tabular-nums text-muted-foreground" />
            </div>
            <Button id="filter-out" variant="ghost" fullWidth="true" className="justify-start rounded-xl" label="@utils.str.concat(values=[filter.name, ' · ', filter.center_wavelength, '/', filter.bandwidth, ' nm'])" onClick="@self.switch_filter(filter.slot)" />
        </if>
    </foreach>
</div>"""

#: Exposure in milliseconds (the state keeps seconds).
_EXPOSURE_MS = "utils.math.multiply(values=[camera.current_exposure_time, 1000])"
#: The share of the first source's power.
_POWER = (
    "utils.math.divide("
    "a=utils.obj.get(value=utils.list.first(value=self.IlluminationState.illuminations), path='intensity'), "
    "b=utils.obj.get(value=utils.list.first(value=self.IlluminationState.illuminations), path='max_intensity'))"
)

#: The cameras as photon collectors: exposure, gain, and the light a frame costs.
DETECTION = f"""
<div className="flex flex-col gap-3">
    <foreach items="@self.CameraState.detectors" let="#camera">
        <div className="{TILE}">
            <div className="flex items-center gap-2">
                <div className="flex flex-col">
                    <span text="Detection" className="{EYEBROW}" />
                    <span text="@camera.name" className="truncate text-sm font-medium" />
                </div>
                <div className="ml-auto">
                    <if when="@self.CameraState.is_acquiring" then="camera-live" else="camera-idle">
                        <div id="camera-live" className="flex items-center gap-1.5 rounded-full bg-red-500/15 px-2.5 py-1 text-[11px] font-medium text-red-300">
                            <span className="size-1.5 animate-pulse rounded-full bg-red-400" />
                            <span text="Live" />
                        </div>
                        <div id="camera-idle" className="flex items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 text-[11px] text-muted-foreground">
                            <span className="size-1.5 rounded-full bg-white/30" />
                            <span text="Idle" />
                        </div>
                    </if>
                </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="flex min-w-0 flex-col gap-2 rounded-xl bg-white/[0.03] p-3">
                    <span text="Exposure" className="{EYEBROW}" />
                    <div className="flex items-baseline gap-1">
                        <span text="@utils.fmt.number(value={_EXPOSURE_MS}, maximumFractionDigits=1)" className="text-2xl font-semibold tabular-nums" />
                        <span text="ms" className="text-xs text-muted-foreground" />
                    </div>
                    <Slider className="min-w-0 past:hidden" step="0.1" value="@{_EXPOSURE_MS}" min="@utils.math.multiply(values=[camera.min_exposure_time, 1000])" max="@utils.math.multiply(values=[camera.max_exposure_time, 1000])" onCommit="@self.update_detector(camera.slot, exposure_time=utils.math.divide(a=event, b=1000))" />
                </div>
                <div className="flex min-w-0 flex-col gap-2 rounded-xl bg-white/[0.03] p-3">
                    <span text="Gain" className="{EYEBROW}" />
                    <div className="flex items-baseline gap-1">
                        <span text="@utils.fmt.number(value=camera.current_gain, maximumFractionDigits=1)" className="text-2xl font-semibold tabular-nums" />
                        <span text="dB" className="text-xs text-muted-foreground" />
                    </div>
                    <Slider className="min-w-0 past:hidden" step="0.1" value="@camera.current_gain" min="@camera.min_gain" max="@camera.max_gain" onCommit="@self.update_detector(camera.slot, gain=event)" />
                </div>
            </div>
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-amber-300/15 bg-amber-300/5 px-3 py-2">
                <span text="Light per frame" className="text-xs text-amber-200/80" />
                <span text="@utils.str.concat(values=[utils.fmt.number(value={_EXPOSURE_MS}, maximumFractionDigits=1), ' ms at ', utils.fmt.percent(value={_POWER})])" className="ml-auto text-xs font-medium tabular-nums text-amber-200" />
            </div>
            <span text="Longer and brighter collects more photons, and bleaches more." className="mt-2 block text-[11px] text-muted-foreground" />
        </div>
    </foreach>
</div>"""


def _pill(id: str, dot: str, text: str, tone: str) -> str:  # noqa: A002
    return f"""
        <div id="{id}" className="flex items-center gap-1.5 rounded-full border border-white/10 bg-zinc-950/70 px-2.5 py-1 text-[11px] {tone} backdrop-blur">
            <span className="size-1.5 rounded-full {dot}" />
            <span text="{text}" />
        </div>"""


#: At a glance: is the sample lit, is the camera streaming, is the light path calibrated.
READINESS = f"""
<div className="flex flex-wrap gap-1.5">
    <if when="@utils.list.includes(value=utils.list.pluck(value=self.IlluminationState.illuminations, path='is_active'), search=True)" then="ready-light" else="ready-dark">{_pill("ready-light", "bg-sky-400 shadow-[0_0_8px_2px] shadow-sky-400/60", "Lit", "text-sky-200")}{_pill("ready-dark", "bg-white/30", "Dark", "text-muted-foreground")}
    </if>
    <if when="@self.CameraState.is_acquiring" then="ready-live" else="ready-idle">{_pill("ready-live", "animate-pulse bg-red-400", "Streaming", "text-red-200")}{_pill("ready-idle", "bg-white/30", "Idle", "text-muted-foreground")}
    </if>
    <if when="@utils.list.isEmpty(value=self.CalibrationState.calibrated_light_paths)" then="ready-uncalibrated" else="ready-calibrated">{_pill("ready-uncalibrated", "bg-amber-400", "Uncalibrated", "text-amber-200")}{_pill("ready-calibrated", "bg-emerald-400", "Calibrated", "text-emerald-200")}
    </if>
</div>"""

#: Taking an image (a shutter button), or, while no light path is calibrated (an image
#: would have no pixel size and no place on the stage), the call to calibrate it.
ACQUIRE_OR_CALIBRATE = """
<if when="@utils.list.isEmpty(value=self.CalibrationState.calibrated_light_paths)" then="calibrate" else="acquire">
    <div id="calibrate" className="flex items-center gap-3 rounded-2xl border border-amber-400/30 bg-zinc-950/80 p-3 shadow-xl backdrop-blur past:hidden">
        <div className="flex min-w-0 flex-1 flex-col">
            <span text="Light path not calibrated" className="text-sm font-medium text-amber-200" />
            <span text="Calibrate once: images then get their pixel size and their place on the stage." className="text-xs text-muted-foreground" />
        </div>
        <Button label="Calibrate" icon="wand" size="sm" className="shrink-0 rounded-full bg-amber-400 text-black hover:bg-amber-300" onClick="@self.calibrate_light_path()" />
    </div>
    <Button id="acquire" label="Acquire" icon="camera" size="lg" fullWidth="true" className="h-12 rounded-full text-base shadow-xl past:hidden" onClick="@self.capture_image()" />
</if>"""

#: Starting and stopping the live view.
LIVE_BUTTONS = """
<div className="flex gap-1 rounded-full border border-white/10 bg-zinc-950/70 p-1 backdrop-blur past:hidden">
    <Button label="Live" icon="play" size="sm" variant="ghost" className="rounded-full" onClick="@self.start_live_view()" />
    <Button label="Stop" icon="square" size="sm" variant="ghost" className="rounded-full" onClick="@self.stop_live_view()" />
</div>"""


def fluorescence_ui(has_filters: bool) -> str:
    """The fluorescence view: the image large, the light path's controls beside it."""
    return f"""
<div className="flex h-full w-full gap-4 overflow-hidden bg-[radial-gradient(ellipse_at_top_left,rgba(56,189,248,0.06),transparent_50%)] p-4">
    <ScrollArea className="h-full w-[380px] shrink-0">
        <div className="flex flex-col gap-3 pb-4 pr-3">{READINESS}{EXCITATION}{EMISSION if has_filters else ""}{DETECTION}
        </div>
    </ScrollArea>
    <div className="relative min-w-0 flex-1 overflow-hidden rounded-2xl border border-white/10 bg-black shadow-2xl">
        <div className="h-full past:opacity-40">
            <LiveView className="h-full" />
        </div>
        <div className="absolute bottom-5 right-4">{LIVE_BUTTONS}
        </div>
        <div className="absolute bottom-5 left-1/2 w-[min(26rem,80%)] -translate-x-1/2">{ACQUIRE_OR_CALIBRATE}
        </div>
    </div>
</div>"""


def blok(has_filters: bool) -> BlokEntry:
    """The fluorescence view."""
    return BlokEntry(
        bsx=fluorescence_ui(has_filters),
        description="Fluorescence: excitation, emission and detection, built from blok primitives.",
    )
