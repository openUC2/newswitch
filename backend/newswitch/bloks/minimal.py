"""The minimal view: just the live image and the stage.

The live view fills the screen, with buttons to start and stop it; the stage's controls
sit beside it. For moving around a sample by eye.

Used only by ``python -m newswitch.tools.build_design``, which writes the bloks into a
configuration's ``ui``; newswitch itself reads them from there.
"""

from newswitch.bloks.fluorescence import ACQUIRE_OR_CALIBRATE
from newswitch.config_io import BlokEntry

MINIMAL_UI = f"""
<Resizable direction="row" className="h-full w-full">
    <ResizablePanel defaultSize="70">
        <div className="flex h-full flex-col gap-3 p-4">
            <div className="flex gap-2 past:hidden">
                <Button label="Start live view" icon="play" onClick="@self.start_live_view()" />
                <Button label="Stop" icon="square" variant="outline" onClick="@self.stop_live_view()" />
            </div>
            <div className="min-h-0 flex-1 overflow-hidden rounded-lg past:opacity-40">
                <LiveView className="h-full" />
            </div>
        </div>
    </ResizablePanel>
    <ResizableHandle withHandle="true" />
    <ResizablePanel defaultSize="30" minSize="20" maxSize="45">
        <ScrollArea className="h-full">
            <div className="p-4 past:opacity-70 past:grayscale">
                <StageControl className="locked:opacity-60" />
                {ACQUIRE_OR_CALIBRATE}
            </div>
        </ScrollArea>
    </ResizablePanel>
</Resizable>
"""


NAME = "view-minimal"


def blok(default: bool) -> BlokEntry:
    """The minimal view."""
    return BlokEntry(
        bsx=MINIMAL_UI,
        description="Minimal: the live image and the stage, nothing else.",
        default=default,
    )
