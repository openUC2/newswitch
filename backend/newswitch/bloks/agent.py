"""The agent-mode view of a microscope: its camera streams, for Orkestrator.

Written against Orkestrator's standard catalog (`AGENT_CATALOG`), not the newswitch
frontend's: in agent mode Orkestrator renders the bloks. The detectors' lovekit streams
(`newswitch.broadcasters.lovekit.CameraStreams`) are shown as structures, Orkestrator opens them;
beside them, starting and stopping the live view, acquiring, and homing a stage.

A configuration built from an optikit design also gets its 3D view here (`SCENE_NAME`, a
scene; composed by `newswitch.design`'s ``agent_bloks``): the model moves and lights up
with the states, the camera streams float at the camera while it acquires, and a click on
a device opens its card (`CARDS`). The cards are bare controls, the popout is a card already.

Used only by ``python -m newswitch.design.build``, which writes the bloks into a
configuration's ``agent_ui``; newswitch itself reads them from there.
"""

from arkitekt_spec.declare.catalogs import STANDARD_CATALOG_NAME, standard_catalog_release

from newswitch.config_io import BlokEntry

NAME = "view-microscope"

#: The catalog the agent-mode bloks are written against: the one arkitekt ships.
AGENT_CATALOG = f"{STANDARD_CATALOG_NAME}@{standard_catalog_release()}"


def microscope_view(has_stage: bool) -> str:
    """The camera streams and the live view's buttons; homing when there is a stage."""
    home = (
        '\n        <Button label="Home stage" icon="home" onClick="@self.move_home()" />'
        if has_stage
        else ""
    )
    return f"""
<div className="flex flex-col gap-4 p-4">
    <Card>
        <CardHeader><CardTitle text="Cameras" /></CardHeader>
        <CardContent>
            <foreach items="@self.CameraStreams.streams" let="#stream">
                <StructureDisplay value="@stream" />
            </foreach>
        </CardContent>
    </Card>
    <div className="flex gap-2">
        <Button label="Start live view" icon="play" onClick="@self.start_live_view()" />
        <Button label="Stop" icon="square" onClick="@self.stop_live_view()" />
        <Button label="Acquire" icon="camera" onClick="@self.capture_image()" />{home}
    </div>
</div>"""


def blok(has_stage: bool) -> BlokEntry:
    """The agent-mode view."""
    return BlokEntry(
        bsx=microscope_view(has_stage),
        description="Microscope: the camera streams, live view and acquiring.",
        default=True,
    )


#: The 3D view: a scene, shown first.
SCENE_NAME = "view-3d"

#: Device kind -> the card a click on it opens in the 3D view.
CARDS = {"camera": "agent-camera", "laser": "agent-laser", "stage": "agent-stage"}

#: The camera streams floating at the camera while it acquires.
LIVE_POPOUT = """
<Popout node="{node}" open="@self.CameraState.is_acquiring">
    <div className="w-[320px] overflow-hidden rounded-md">
        <foreach items="@self.CameraStreams.streams" let="#stream">
            <StructureDisplay value="@stream" className="w-full" />
        </foreach>
    </div>
</Popout>"""

_CAMERA_CARD = """
<div className="grid w-[340px] gap-3">
    <foreach items="@self.CameraStreams.streams" let="#stream">
        <StructureDisplay value="@stream" className="w-full" />
    </foreach>
    <div className="flex gap-2">
        <Button label="Start live view" icon="play" onClick="@self.start_live_view()" />
        <Button label="Stop" icon="square" variant="outline" onClick="@self.stop_live_view()" />
        <Button label="Acquire" icon="camera" variant="secondary" onClick="@self.capture_image()" />
    </div>
</div>"""

_LASER_CARD = """
<div className="grid w-[300px] gap-3">
    <foreach items="@self.IlluminationState.illuminations" let="#light">
        <div className="flex items-center justify-between gap-3">
            <div className="grid">
                <Text weight="medium" text="@utils.str.concat(values=[light.wavelength, ' nm'])" />
                <Text size="xs" tone="muted" text="@utils.str.concat(values=['Channel ', light.slot])" />
            </div>
            <div className="flex gap-2">
                <Button label="On" size="sm" disabled="@light.is_active" onClick="@self.turn_on_illumination(channel=light.slot)" />
                <Button label="Off" size="sm" variant="outline" onClick="@self.turn_off_illumination_channel(channel=light.slot)" />
            </div>
        </div>
    </foreach>
</div>"""


def _readout(label: str, path: str) -> str:
    return f"""
        <div className="rounded-md border bg-muted/40 px-3 py-2">
            <Text size="xs" tone="muted" text="{label}" />
            <Text mono="true" weight="semibold" text="@utils.fmt.number(value={path}, maximumFractionDigits=0)" />
        </div>"""


_STAGE_CARD = f"""
<div className="grid w-[300px] gap-3">
    <div className="grid grid-cols-3 gap-2">{"".join(_readout(f"{axis.upper()} (µm)", f"self.StageState.{axis}") for axis in "xyz")}
    </div>
    <Button label="Home stage" icon="home" variant="outline" onClick="@self.move_home()" />
</div>"""

_CARD_SOURCES = {"camera": _CAMERA_CARD, "laser": _LASER_CARD, "stage": _STAGE_CARD}


def card(kind: str) -> BlokEntry:
    """The card a click on a device of `kind` opens in the 3D view."""
    return BlokEntry(
        bsx=_CARD_SOURCES[kind],
        description=f"The design's {kind}: opens where it is clicked in the 3D view.",
    )


def scene_blok(tree: str, design: str) -> BlokEntry:
    """The 3D view of the design `design` (its scene tree `tree`), shown first in a scene."""
    return BlokEntry(
        bsx=tree,
        description=f"3D: the microscope of the design {design}; the stage follows it, laser and camera light up while on, click a device for its controls.",
        context="scene",
        default=True,
    )
