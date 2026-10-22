"""The UI of a microscope described by an optikit design.

The design's 3D model is the main stage: its stage parts move with `StageState`, its
laser glows while on, its camera glows while acquiring (with the live view popping out),
and a click on a device opens its controls. Beside it are the controls of the devices the
design has, and only those.

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

#: The live view floating at the camera while it acquires.
LIVE_POPOUT = """
<Popout node="{node}" open="@self.CameraState.is_acquiring">
    <div className="w-[360px] overflow-hidden rounded-md"><LiveView /></div>
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


def controls(config: NewswitchConfig) -> list[str]:
    """The control panels of the devices the configuration has, camera first."""
    panels = []
    if adapters.detectors(config) is not None:
        panels.append("<CameraControl />")
    if adapters.illuminations(config) is not None:
        panels.append("<IlluminationControl />")
    if adapters.motion_stage(config) is not None:
        panels.append("<StageControl />")
    return panels


def design_ui(dsn: Path, model: optikit.Model, config: NewswitchConfig) -> str:
    """The generated UI: the 3D microscope on the main stage, its controls beside it."""
    panels = "\n                ".join(controls(config))
    return f"""
<Resizable direction="row" className="h-full w-full">
    <ResizablePanel defaultSize="70">
        <div className="h-full w-full bg-muted/30">{scene_tree(dsn, model, config)}
        </div>
    </ResizablePanel>
    <ResizableHandle withHandle="true" />
    <ResizablePanel defaultSize="30" minSize="20" maxSize="45">
        <ScrollArea className="h-full">
            <div className="flex flex-col gap-4 p-4">
                {panels}
            </div>
        </ScrollArea>
    </ResizablePanel>
</Resizable>
"""


def declare(dsn: Path, config: NewswitchConfig, catalog: str) -> None:
    """Declare the design's model asset, its device cards and its UI as the default blok."""
    model_path, model = build_model(dsn)
    root = Path(arkitekt_app.__file__).parent
    nsapp.register_asset(MODEL_ASSET, str(model_path.relative_to(root)))

    cards = {
        CAMERA_CARD: (
            "<div className='flex flex-col gap-4'><CameraControl /><LiveView /></div>",
            adapters.detectors(config),
        ),
        LASER_CARD: ("<IlluminationControl />", adapters.illuminations(config)),
        STAGE_CARD: ("<StageControl />", adapters.motion_stage(config)),
    }
    for name, (tree, present) in cards.items():
        if present is not None:
            nsapp.blok(
                name,
                bsx(tree),
                description=f"The design's {name.removeprefix('design-')}.",
                catalog=catalog,
                mode="strict",
            )

    own = dsn / DESIGN_UI_FILE
    tree = own.read_text(encoding="utf-8") if own.is_file() else design_ui(dsn, model, config)
    nsapp.blok(
        "design",
        bsx(tree),
        description=f"The microscope of the design {dsn.name}: in 3D, with its controls.",
        catalog=catalog,
        context="html",
        default=True,
        mode="strict",
    )
