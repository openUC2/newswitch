"""The minimal microscope UI: just a camera and a stage.

The camera's controls on the left, the stage view in the middle (the stage, its axes, the
live image and the frames taken), the stage's controls on the right.
"""

from arkitekt import bsx

from newswitch.arkitekt_app import nsapp
from newswitch.bloks.catalog import CATALOG_NAME

MINIMAL_UI = """
<Resizable direction="row" className="h-full w-full">
    <ResizablePanel defaultSize="22" minSize="15" maxSize="35">
        <ScrollArea className="h-full">
            <div className="p-4"><CameraControl /></div>
        </ScrollArea>
    </ResizablePanel>
    <ResizableHandle withHandle="true" />
    <ResizablePanel defaultSize="53">
        <div className="flex h-full flex-col overflow-hidden bg-muted/30">
            <StageView className="flex-1">
                <StageScene>
                    <StageAxis />
                    <StagePlane />
                    <LivesLayer />
                    <FramesLayer />
                    <StagePositioner />
                </StageScene>
                <SceneOverlay />
            </StageView>
        </div>
    </ResizablePanel>
    <ResizableHandle withHandle="true" />
    <ResizablePanel defaultSize="25" minSize="15" maxSize="40">
        <ScrollArea className="h-full">
            <div className="p-4"><StageControl /></div>
        </ScrollArea>
    </ResizablePanel>
</Resizable>
"""


def declare() -> None:
    """Declare the minimal UI as the default blok."""
    nsapp.blok(
        "minimal",
        bsx(MINIMAL_UI),
        description="A minimal microscope: just a camera and a stage.",
        catalog=CATALOG_NAME,
        context="html",
        default=True,
        mode="strict",
    )
