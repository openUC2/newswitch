"""The standard microscope UI: what the frontend shows by default.

Settings on the left, the stage view in the middle (the 3D scene and the panels
floating over it), stage control and acquisition on the right. Built in the
newswitch catalog and checked strictly: a component or prop the frontend does
not know fails at import, not in the browser.
"""

from arkitekt import bsx

from newswitch.arkitekt_app import nsapp
from newswitch.bloks.catalog import CATALOG_NAME

STANDARD_UI = """
<Resizable direction="row" className="h-full w-full">
    <ResizablePanel defaultSize="15" minSize="10" maxSize="30">
        <SettingsPanel className="h-full past:opacity-70 past:grayscale" />
    </ResizablePanel>
    <ResizableHandle withHandle="true" />
    <ResizablePanel defaultSize="55">
        <div className="flex h-full flex-col overflow-hidden bg-muted/30">
            <StageView className="flex-1">
                <StageScene>
                    <FrameLightPathLayer />
                    <StageAxis />
                    <FramesLayer />
                    <StagePlane />
                    <LivesLayer />
                    <LightPathLayer />
                    <ImagesLayer />
                    <StagePositioner />
                    <RectangleDrawer />
                </StageScene>
                <ScanRegionPanel />
                <ImageMetadataPanel />
                <KubeStatePanel />
                <FramePanel />
                <SceneOverlay />
                <DebugOverlay />
            </StageView>
        </div>
    </ResizablePanel>
    <ResizableHandle withHandle="true" />
    <ResizablePanel defaultSize="30" minSize="15" maxSize="40">
        <ScrollArea className="h-full">
            <div className="flex flex-col gap-4 p-4 past:opacity-70 past:grayscale">
                <StageControl className="locked:opacity-60" />
                <MultidimensionalAcquisitionControl className="locked:opacity-60" />
                <CalibrateLightPath className="locked:opacity-60" />
                <BloksPanel />
            </div>
        </ScrollArea>
    </ResizablePanel>
</Resizable>
"""


def declare() -> None:
    """Declare the standard UI as the default blok."""
    nsapp.blok(
        "standard",
        bsx(STANDARD_UI),
        description="The default newswitch microscope UI.",
        catalog=CATALOG_NAME,
        context="html",
        default=True,
        mode="strict",
    )
