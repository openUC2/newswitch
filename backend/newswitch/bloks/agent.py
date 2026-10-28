"""The agent-mode view of a microscope: its camera streams, for Orkestrator.

Written against the spec's catalogs and Orkestrator's module (`AGENT_CATALOG`), not the
newswitch frontend's module: in agent mode Orkestrator renders the bloks. The detectors' lovekit streams
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
        '\n        <Button icon="home" onClick={self.move_home()}>Home stage</Button>'
        if has_stage
        else ""
    )
    return f"""
<Html>
<div className="flex flex-col gap-4 p-4">
    <Card>
        <CardHeader><CardTitle>Cameras</CardTitle></CardHeader>
        <CardContent>
            <foreach items={{self.CameraStreams.streams}} let="stream">
                <StructureDisplay value={{stream}} />
            </foreach>
        </CardContent>
    </Card>
    <div className="flex gap-2">
        <Button icon="play" onClick={{self.start_live_view()}}>Start live view</Button>
        <Button icon="square" onClick={{self.stop_live_view()}}>Stop</Button>
        <Button icon="camera" onClick={{self.capture_image()}}>Acquire</Button>{home}
    </div>
</div>
</Html>"""


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
<Popout node="{node}" open={{self.CameraState.is_acquiring}}>
    <div className="w-[320px] overflow-hidden rounded-md">
        <foreach items={{self.CameraStreams.streams}} let="stream">
            <StructureDisplay value={{stream}} className="w-full" />
        </foreach>
    </div>
</Popout>"""

_CAMERA_CARD = """
<Html>
<div className="grid w-[340px] gap-3">
    <foreach items={self.CameraStreams.streams} let="stream">
        <StructureDisplay value={stream} className="w-full" />
    </foreach>
    <div className="flex gap-2">
        <Button icon="play" onClick={self.start_live_view()}>Start live view</Button>
        <Button icon="square" variant="outline" onClick={self.stop_live_view()}>Stop</Button>
        <Button icon="camera" variant="secondary" onClick={self.capture_image()}>Acquire</Button>
    </div>
</div>
</Html>"""

_LASER_CARD = """
<Html>
<div className="grid w-[300px] gap-3">
    <foreach items={self.IlluminationState.illuminations} let="light" key={light.slot}>
        <div className="flex items-center justify-between gap-3">
            <div className="grid">
                <Text weight="medium">{light.wavelength} nm</Text>
                <Text size="xs" tone="muted">Channel {light.slot}</Text>
            </div>
            <div className="flex gap-2">
                <Button size="sm" disabled={light.is_active} onClick={self.turn_on_illumination(channel: light.slot)}>On</Button>
                <Button size="sm" variant="outline" onClick={self.turn_off_illumination_channel(channel: light.slot)}>Off</Button>
            </div>
        </div>
    </foreach>
</div>
</Html>"""


def _readout(label: str, path: str) -> str:
    return f"""
        <div className="rounded-md border bg-muted/40 px-3 py-2">
            <Text size="xs" tone="muted">{label}</Text>
            <Text mono={{true}} weight="semibold">{{fmt.number(value: {path}, digits: 0)}}</Text>
        </div>"""


_STAGE_CARD = f"""
<Html>
<div className="grid w-[300px] gap-3">
    <div className="grid grid-cols-3 gap-2">{"".join(_readout(f"{axis.upper()} (µm)", f"self.StageState.{axis}") for axis in "xyz")}
    </div>
    <Button icon="home" variant="outline" onClick={{self.move_home()}}>Home stage</Button>
</div>
</Html>"""

_CARD_SOURCES = {"camera": _CAMERA_CARD, "laser": _LASER_CARD, "stage": _STAGE_CARD}


def card(kind: str) -> BlokEntry:
    """The card a click on a device of `kind` opens in the 3D view."""
    return BlokEntry(
        bsx=_CARD_SOURCES[kind],
        description=f"The design's {kind}: opens where it is clicked in the 3D view.",
    )


def scene_blok(tree: str, design: str) -> BlokEntry:
    """The 3D view of the design `design` (its scene tree `tree`, a ``<Scene>``), shown first."""
    return BlokEntry(
        bsx=tree,
        description=f"3D: the microscope of the design {design}; the stage follows it, laser and camera light up while on, click a device for its controls.",
        default=True,
    )
