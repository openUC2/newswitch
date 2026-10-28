"""The stage view: where the sample is, and what was imaged there.

The stage scene fills the screen: the stage and its axes, the live image, the frames and
images taken (placed where they were taken), with the panels that float over it. The
stage's and the camera's controls are beside it.

Used only by ``python -m newswitch.tools.build_design``, which writes the bloks into a
configuration's ``ui``; newswitch itself reads them from there.
"""

from newswitch.bloks.fluorescence import ACQUIRE_OR_CALIBRATE
from newswitch.config_io import BlokEntry

STAGE_UI = f"""
<Html>
<Resizable direction="row" className="h-full w-full">
    <ResizablePanel defaultSize={{70}}>
        <div className="flex h-full flex-col overflow-hidden bg-muted/30">
            <StageView className="flex-1">
                <StageScene>
                    <StageAxis />
                    <StagePlane />
                    <FramesLayer />
                    <ImagesLayer />
                    <LivesLayer />
                    <FrameLightPathLayer />
                    <StagePositioner />
                    <RectangleDrawer />
                </StageScene>
                <ScanRegionPanel />
                <ImageMetadataPanel />
                <FramePanel />
                <SceneOverlay />
            </StageView>
        </div>
    </ResizablePanel>
    <ResizableHandle withHandle={{true}} />
    <ResizablePanel defaultSize={{30}} minSize={{20}} maxSize={{45}}>
        <ScrollArea className="h-full">
            <div className="flex flex-col gap-4 p-4 past:opacity-70 past:grayscale">
                <StageControl className="locked:opacity-60" />
                {ACQUIRE_OR_CALIBRATE}
                <CameraControl className="locked:opacity-60" />
            </div>
        </ScrollArea>
    </ResizablePanel>
</Resizable>
</Html>
"""


NAME = "view-stage"


def blok(default: bool) -> BlokEntry:
    """The stage view."""
    return BlokEntry(
        bsx=STAGE_UI,
        description="Stage: the sample on the stage, with the images taken there.",
        default=default,
    )
