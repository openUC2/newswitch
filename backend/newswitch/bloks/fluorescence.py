"""Fluorescence controls built from blok primitives.

Nothing here is a built-in panel: every control is a catalog primitive (Card, Switch,
Slider, Progress, Badge, ``foreach``, ``if``) bound to newswitch's states and
calling its actions, with the util functions (``str.concat``, ``fmt.*``, ``math.*``,
``list.*``) doing the arithmetic. A design (or anyone writing a blok) can rearrange or
replace them without touching the frontend.

The fragments use fixed node ids for their ``if`` branches: each may appear once per blok.
"""

from arkitekt import bsx

from newswitch.arkitekt_app import nsapp

#: Taking an image, or, while no light path is calibrated (an image would have no pixel
#: size and no place on the stage), calibrating it.
ACQUIRE_OR_CALIBRATE = """
<if when="@utils.list.isEmpty(value=self.CalibrationState.calibrated_light_paths)" then="calibrate" else="acquire">
    <div id="calibrate" className="flex flex-col gap-2 past:hidden">
        <Alert title="Light path not calibrated" description="Calibrate once, so images get their pixel size and their place on the stage." icon="alert-triangle" />
        <Button label="Calibrate light path" icon="wand" fullWidth="true" onClick="@self.calibrate_light_path()" />
    </div>
    <Button id="acquire" label="Acquire image" icon="camera" fullWidth="true" className="past:hidden" onClick="@self.capture_image()" />
</if>"""

#: The light sources: on/off, and power (slider, bar and percent) while on.
EXCITATION = """
<div className="flex flex-col gap-3">
    <foreach items="@self.IlluminationState.illuminations" let="#light">
        <div className="flex flex-col gap-2 rounded-lg border border-border/60 p-3">
            <div className="flex items-center gap-2">
                <Text text="@utils.str.concat(values=[light.wavelength, ' nm'])" weight="semibold" />
                <Badge text="@light.kind" variant="outline" />
                <div className="ml-auto past:pointer-events-none">
                    <if when="@light.is_active" then="light-on" else="light-off">
                        <Switch id="light-on" checked="true" label="On" onChange="@self.turn_off_illumination_channel(light.slot)" />
                        <Switch id="light-off" checked="false" label="Off" onChange="@self.turn_on_illumination(channel=light.slot)" />
                    </if>
                </div>
            </div>
            <if when="@light.is_active" then="light-power" else="light-dark">
                <div id="light-power" className="flex flex-col gap-2">
                    <Slider className="past:hidden" value="@light.intensity" min="@light.min_intensity" max="@light.max_intensity" onCommit="@self.set_illumination_intensity(event, channel=light.slot)" />
                    <div className="flex items-center gap-2">
                        <Progress value="@light.intensity" max="@light.max_intensity" />
                        <Text text="@utils.fmt.percent(value=utils.math.divide(a=light.intensity, b=light.max_intensity))" size="xs" mono="true" />
                    </div>
                </div>
                <Text id="light-dark" text="Off: no excitation" size="xs" tone="muted" />
            </if>
        </div>
    </foreach>
</div>"""

#: The emission filters: the one in the light path is solid, a click switches.
EMISSION = """
<div className="flex flex-col gap-2 past:pointer-events-none">
    <foreach items="@self.FilterBankState.filters" let="#filter">
        <if when="@utils.compare.eq(a=filter.slot, b=self.FilterBankState.current_slot)" then="filter-in" else="filter-out">
            <Button id="filter-in" icon="filter" fullWidth="true" label="@utils.str.concat(values=[filter.name, ' · ', filter.center_wavelength, '/', filter.bandwidth, ' nm'])" />
            <Button id="filter-out" icon="filter" variant="outline" fullWidth="true" label="@utils.str.concat(values=[filter.name, ' · ', filter.center_wavelength, '/', filter.bandwidth, ' nm'])" onClick="@self.switch_filter(filter.slot)" />
        </if>
    </foreach>
</div>"""

#: The cameras: exposure in milliseconds (the state keeps seconds) and gain.
DETECTION = """
<div className="flex flex-col gap-4">
    <foreach items="@self.CameraState.detectors" let="#camera">
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <Text text="@camera.name" weight="semibold" truncate="true" />
                <div className="ml-auto">
                    <if when="@self.CameraState.is_acquiring" then="camera-live" else="camera-idle">
                        <Badge id="camera-live" text="Live" icon="video" />
                        <Badge id="camera-idle" text="Idle" variant="outline" />
                    </if>
                </div>
            </div>
            <div className="flex items-center justify-between">
                <Text text="Exposure" size="sm" />
                <Text text="@utils.str.concat(values=[utils.fmt.number(value=utils.math.multiply(values=[camera.current_exposure_time, 1000]), maximumFractionDigits=1), ' ms'])" size="sm" mono="true" />
            </div>
            <Slider className="past:hidden" step="0.1" value="@utils.math.multiply(values=[camera.current_exposure_time, 1000])" min="@utils.math.multiply(values=[camera.min_exposure_time, 1000])" max="@utils.math.multiply(values=[camera.max_exposure_time, 1000])" onCommit="@self.update_detector(camera.slot, exposure_time=utils.math.divide(a=event, b=1000))" />
            <div className="flex items-center justify-between">
                <Text text="Gain" size="sm" />
                <Text text="@utils.fmt.number(value=camera.current_gain, maximumFractionDigits=1)" size="sm" mono="true" />
            </div>
            <Slider className="past:hidden" step="0.1" value="@camera.current_gain" min="@camera.min_gain" max="@camera.max_gain" onCommit="@self.update_detector(camera.slot, gain=event)" />
        </div>
    </foreach>
</div>"""

#: At a glance: is there excitation, is the camera streaming, is the light path calibrated.
READINESS = """
<div className="flex flex-wrap gap-2">
    <if when="@utils.list.includes(value=utils.list.pluck(value=self.IlluminationState.illuminations, path='is_active'), search=True)" then="ready-light" else="ready-dark">
        <Badge id="ready-light" text="Excitation on" icon="zap" />
        <Badge id="ready-dark" text="Excitation off" icon="zap" variant="outline" />
    </if>
    <if when="@self.CameraState.is_acquiring" then="ready-live" else="ready-idle">
        <Badge id="ready-live" text="Live" icon="video" />
        <Badge id="ready-idle" text="Camera idle" icon="video" variant="outline" />
    </if>
    <if when="@utils.list.isEmpty(value=self.CalibrationState.calibrated_light_paths)" then="ready-uncalibrated" else="ready-calibrated">
        <Badge id="ready-uncalibrated" text="Not calibrated" icon="alert-triangle" variant="destructive" />
        <Badge id="ready-calibrated" text="Calibrated" icon="check" variant="secondary" />
    </if>
</div>"""

#: Starting and stopping the live view.
LIVE_BUTTONS = """
<div className="flex gap-2 past:hidden">
    <Button label="Start live view" icon="play" onClick="@self.start_live_view()" />
    <Button label="Stop" icon="square" variant="outline" onClick="@self.stop_live_view()" />
</div>"""


def card(title: str, description: str, body: str) -> str:
    """A titled card around a fragment."""
    return f"""
<Card>
    <CardHeader>
        <CardTitle text="{title}" />
        <CardDescription text="{description}" />
    </CardHeader>
    <CardContent>{body}
    </CardContent>
</Card>"""


def fluorescence_ui(has_filters: bool) -> str:
    """The fluorescence view: the light path's controls on the left, the image on the right."""
    cards = [
        card("Excitation", "The light sources and their power.", EXCITATION),
        *(
            [card("Emission", "The filter in front of the camera.", EMISSION)]
            if has_filters
            else []
        ),
        card("Detection", "Exposure and gain.", DETECTION),
    ]
    return f"""
<div className="flex h-full w-full gap-4 overflow-hidden p-4">
    <ScrollArea className="h-full w-[380px] shrink-0">
        <div className="flex flex-col gap-4 pr-3 past:opacity-80">{READINESS}{"".join(cards)}
        </div>
    </ScrollArea>
    <div className="flex min-w-0 flex-1 flex-col gap-3">{LIVE_BUTTONS}
        <div className="min-h-0 flex-1 overflow-hidden rounded-lg past:opacity-40">
            <LiveView className="h-full" />
        </div>
        <div className="max-w-sm">{ACQUIRE_OR_CALIBRATE}
        </div>
    </div>
</div>"""


def declare(catalog: str, has_filters: bool) -> None:
    """Declare the fluorescence view."""
    nsapp.blok(
        "view-fluorescence",
        bsx(fluorescence_ui(has_filters)),
        description="Fluorescence: excitation, emission and detection, built from blok primitives.",
        catalog=catalog,
        context="html",
        mode="strict",
    )
