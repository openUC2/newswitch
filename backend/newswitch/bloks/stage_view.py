"""The stage view: where the sample is, and what was imaged there.

The stage scene fills the screen: the stage and its axes, the live image, the frames and
images taken (placed where they were taken), with the panels that float over it. The
stage's and the camera's controls are beside it.
"""

from arkitekt import bsx

from newswitch.arkitekt_app import nsapp
from newswitch.bloks.catalog import CATALOG_NAME

STAGE_UI = """
<Resizable direction="row" className="h-full w-full">
    <ResizablePanel defaultSize="70">
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
    <ResizableHandle withHandle="true" />
    <ResizablePanel defaultSize="30" minSize="20" maxSize="45">
        <ScrollArea className="h-full">
            <div className="flex flex-col gap-4 p-4 past:opacity-70 past:grayscale">
                <StageControl className="locked:opacity-60" />
                <CameraControl className="locked:opacity-60" />
            </div>
        </ScrollArea>
    </ResizablePanel>
</Resizable>
"""


def declare(default: bool) -> None:
    """Declare the stage view."""
    nsapp.blok(
        "view-stage",
        bsx(STAGE_UI),
        description="Stage: the sample on the stage, with the images taken there.",
        catalog=CATALOG_NAME,
        context="html",
        default=default,
        mode="strict",
    )
