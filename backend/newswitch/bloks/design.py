"""The UI of a microscope described by an optikit design.

The design's 3D model is the main stage: its stage parts move with `StageState`, its
laser glows while on, its camera glows while acquiring (with the live view popping out),
and a click on a device opens its controls (cards for the devices the design has, and only
those). Nothing else is on screen; the bottom bar switches to the other views.

A design may bring its own UI: a ``newswitch-ui.bsx`` in its folder is the default blok
then (checked against the newswitch catalog like any other), and the design is the source
of the microscope's UI. The device cards and the model asset are declared either way, so
such a blok can use them.
"""

from pathlib import Path

from arkitekt import bsx

from newswitch import arkitekt_app
from newswitch.arkitekt_app import nsapp
from newswitch.config_io import NewswitchConfig, adapters
from newswitch.config_io.devices import LightsourceConfig
from newswitch.optikit import dsn as optikit
from newswitch.design.model import build_model

#: The model's asset name: a blok reads it as ``@self.assets.design``.
MODEL_ASSET = "design"
#: A UI the design brings along, in its folder.
DESIGN_UI_FILE = "newswitch-ui.bsx"

CAMERA_CARD = "design-camera"
STAGE_CARD = "design-stage"
LASER_CARD = "design-laser"

#: Starting and stopping the live view: the camera glows while it streams, and the stream
#: floats at it.
LIVE_BUTTONS = """<div className="flex gap-2 past:hidden">
                    <Button label="Start live view" icon="play" onClick="@self.start_live_view()" />
                    <Button label="Stop" icon="square" variant="outline" onClick="@self.stop_live_view()" />
                </div>"""

#: The live view floating at the camera while it acquires.
LIVE_POPOUT = """
<Popout node="{node}" open="@self.CameraState.is_acquiring">
    <div className="aspect-video w-[360px] overflow-hidden rounded-md"><LiveView /></div>
</Popout>"""


def _axis_inputs(config: NewswitchConfig) -> dict[str, str]:
    """Design input -> stage axis label (``sample-x`` -> ``x``), from the axes' bindings."""
    found = adapters.motion_stage(config)
    if found is None:
        return {}
    _, stage = found
    inputs: dict[str, str] = {}
    for label, axis_key in stage.axes.items():
        variable = getattr(config.devices.get(axis_key), "extras", {}).get("optikit_dsn_variable")
        if variable:
            inputs[str(variable)] = label
    return inputs


def _components(dsn: Path) -> dict[str, list[str]]:
    """Device kind -> the design components that are devices of that kind."""
    kinds: dict[str, list[str]] = {}
    for device in optikit.devices(dsn):
        kinds.setdefault(device.type, []).append(device.component)
    return kinds


def scene_tree(dsn: Path, model: optikit.Model, config: NewswitchConfig) -> str:
    """The 3D view of the design's model, bound to newswitch's states (BSX)."""
    kinds = _components(dsn)
    in_model = [path for paths in kinds.values() for path in paths if path in model.components]

    joints: dict[str, optikit.Bind | str] = {
        name: optikit.Bind(f"@self.StageState.{label}", unit="um")
        for name, label in _axis_inputs(config).items()
        if name in model.joints
    }
    glow: dict[str, optikit.Glow | str] = {}
    opens: dict[str, str] = {}
    children = ""

    sources = [
        key for key, device in config.devices.items() if isinstance(device, LightsourceConfig)
    ]
    for index, path in enumerate(kinds.get("laser", [])):
        if path in in_model and index < len(sources):
            on = f"$state.self.IlluminationState.illuminations.{index}.is_active"
            glow[path] = optikit.Glow(on, color="#38bdf8", intensity=0.6)
            opens[path] = LASER_CARD
    for path in kinds.get("camera", [])[:1]:
        if path in in_model:
            glow[path] = optikit.Glow(
                "@self.CameraState.is_acquiring", color="#22c55e", intensity=0.5
            )
            opens[path] = CAMERA_CARD
            children = LIVE_POPOUT.format(node=model.components[path])
    for path in kinds.get("stage", [])[:1]:
        if path in in_model:
            opens[path] = STAGE_CARD

    return optikit.scene(
        model, asset=MODEL_ASSET, joints=joints, glow=glow, open=opens, children=children
    )


def design_ui(dsn: Path, model: optikit.Model, config: NewswitchConfig) -> str:
    """The generated UI: the 3D microscope, nothing else on screen.

    A device's controls open where it is clicked (its card: `CAMERA_CARD`, `LASER_CARD`,
    `STAGE_CARD`), and the live view floats at the camera while it acquires.
    """
    return f"""
<div className="h-full w-full overflow-hidden bg-muted/30">{scene_tree(dsn, model, config)}
</div>
"""


def declare(dsn: Path, config: NewswitchConfig, catalog: str) -> None:
    """Declare the design's model asset, its device cards and its UI as the default blok."""
    model_path, model = build_model(dsn)
    root = Path(arkitekt_app.__file__).parent
    nsapp.register_asset(MODEL_ASSET, str(model_path.relative_to(root)))

    cards = {
        CAMERA_CARD: (
            f"""<div className="flex w-[380px] flex-col gap-3 past:opacity-80 past:grayscale">
                <CameraControl className="locked:opacity-60" />
                {LIVE_BUTTONS}
                <div className="aspect-video w-full overflow-hidden rounded-md past:hidden"><LiveView /></div>
            </div>""",
            adapters.detectors(config),
        ),
        LASER_CARD: (
            '<div className="w-[340px] past:opacity-80 past:grayscale">'
            '<IlluminationControl className="locked:opacity-60" /></div>',
            adapters.illuminations(config),
        ),
        STAGE_CARD: (
            '<div className="w-[400px] past:opacity-80 past:grayscale">'
            '<StageControl className="locked:opacity-60" /></div>',
            adapters.motion_stage(config),
        ),
    }
    for name, (tree, present) in cards.items():
        if present is not None:
            nsapp.blok(
                name,
                bsx(tree),
                description=f"The design's {name.removeprefix('design-')}: opens where it is clicked.",
                catalog=catalog,
                mode="strict",
            )

    own = dsn / DESIGN_UI_FILE
    tree = own.read_text(encoding="utf-8") if own.is_file() else design_ui(dsn, model, config)
    nsapp.blok(
        "view-3d",
        bsx(tree),
        description=f"3D: the microscope of the design {dsn.name}; click a device for its controls.",
        catalog=catalog,
        context="html",
        default=True,
        mode="strict",
    )
