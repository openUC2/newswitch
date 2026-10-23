"""The UI of a microscope described by an optikit design.

The design's 3D model is the main stage: its stage parts move with `StageState`, its
laser glows while on, its camera glows while acquiring (with the live view popping out),
and a click on a device opens its controls (cards for the devices the design has, and only
those). Nothing else is on screen; the bottom bar switches to the other views.

The same scene is written for agent mode too (`agent_bloks`): Orkestrator renders it, so
its cards and the popout are those of `newswitch.bloks.agent`, in Orkestrator's catalog.

A design may bring its own UI: a ``newswitch-ui.bsx`` in its folder is the 3D view then.
The device cards and the model asset are written either way, so such a blok can use them.

Used only by ``python -m newswitch.tools.build_design``, which writes these bloks into the
design's configuration; newswitch itself reads them from there.
"""

from pathlib import Path

from newswitch.bloks import agent, fluorescence
from newswitch.config_io import BlokEntry, NewswitchConfig, adapters
from newswitch.config_io.devices import LightsourceConfig
from newswitch.design.model import build_model
from newswitch.optikit import dsn as optikit

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


#: Device kind -> the card a click on it opens, in the newswitch frontend.
DESIGN_CARDS = {"camera": CAMERA_CARD, "laser": LASER_CARD, "stage": STAGE_CARD}


def scene_tree(
    dsn: Path,
    model: optikit.Model,
    config: NewswitchConfig,
    cards: dict[str, str] = DESIGN_CARDS,
    popout: str = LIVE_POPOUT,
) -> str:
    """The 3D view of the design's model, bound to newswitch's states (BSX).

    `cards` names the blok a click on a device of each kind opens (a kind it leaves out
    opens nothing), `popout` what floats at the camera while it acquires (``{node}``: the
    camera's node).
    """
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
            if "laser" in cards:
                opens[path] = cards["laser"]
    for path in kinds.get("camera", [])[:1]:
        if path in in_model:
            glow[path] = optikit.Glow(
                "@self.CameraState.is_acquiring", color="#22c55e", intensity=0.5
            )
            if "camera" in cards:
                opens[path] = cards["camera"]
            children = popout.format(node=model.components[path])
    for path in kinds.get("stage", [])[:1]:
        if path in in_model and "stage" in cards:
            opens[path] = cards["stage"]

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


def bloks(dsn: Path, config: NewswitchConfig) -> tuple[dict[str, str], dict[str, BlokEntry]]:
    """The design's assets and bloks: its device cards and the 3D view (the default).

    Builds the model (see `build_model`), so this takes seconds the first time.

    Returns:
        ``(assets, bloks)``: asset name -> path relative to the app's root (``newswitch/``),
        and blok name -> blok.
    """
    model_path, model = build_model(dsn)
    root = Path(__file__).parents[1]  # newswitch/, where assets are found
    assets = {MODEL_ASSET: str(model_path.relative_to(root))}

    cards = {
        CAMERA_CARD: (
            f"""<div className="flex w-[380px] flex-col gap-3 past:opacity-80 past:grayscale">
                {fluorescence.DETECTION}
                {LIVE_BUTTONS}
                <div className="aspect-video w-full overflow-hidden rounded-md past:hidden"><LiveView /></div>
            </div>""",
            adapters.detectors(config),
        ),
        LASER_CARD: (
            f"""<div className="w-[360px] past:opacity-80">{fluorescence.EXCITATION}</div>""",
            adapters.illuminations(config),
        ),
        STAGE_CARD: (
            f"""<div className="flex w-[400px] flex-col gap-3 past:opacity-80 past:grayscale">
                {fluorescence.ACQUIRE_OR_CALIBRATE}
                <StageControl className="locked:opacity-60" />
            </div>""",
            adapters.motion_stage(config),
        ),
    }
    entries = {
        name: BlokEntry(
            bsx=tree,
            description=f"The design's {name.removeprefix('design-')}: opens where it is clicked.",
        )
        for name, (tree, present) in cards.items()
        if present is not None
    }

    own = dsn / DESIGN_UI_FILE
    tree = own.read_text(encoding="utf-8") if own.is_file() else design_ui(dsn, model, config)
    entries["view-3d"] = BlokEntry(
        bsx=tree,
        description=f"3D: the microscope of the design {dsn.name}; click a device for its controls.",
        default=True,
    )
    return assets, entries


def agent_bloks(dsn: Path, config: NewswitchConfig) -> dict[str, BlokEntry]:
    """The design's bloks for agent mode: its device cards, then the 3D view (a scene).

    The cards come first: the scene opens them, and Orkestrator checks that they are there.
    The model asset is the one `bloks` writes (`MODEL_ASSET`).
    """
    _, model = build_model(dsn)
    present = {
        "camera": adapters.detectors(config),
        "laser": adapters.illuminations(config),
        "stage": adapters.motion_stage(config),
    }
    entries = {
        agent.CARDS[kind]: agent.card(kind) for kind, found in present.items() if found is not None
    }
    cards = {kind: agent.CARDS[kind] for kind, found in present.items() if found is not None}
    entries[agent.SCENE_NAME] = agent.scene_blok(
        scene_tree(dsn, model, config, cards=cards, popout=agent.LIVE_POPOUT), dsn.name
    )
    return entries
