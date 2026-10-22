import { Loader2 } from "lucide-react";
import { defaultBlokOf, useBackendUi } from "@/lib/blok/backendUi";
import { BloksPanel } from "../components/bloks/BloksPanel";
import { NewswitchBlok } from "../components/bloks/NewswitchBlok";
import {
  MultidimensionalAcquisitionControl,
  SettingsPanel,
  StageControl,
} from "../components/microscope";
import { CalibrateLightPath } from "../components/microscope/CalibrateLightPath";
import { Expanse } from "../components/stage/Expanse";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "../components/ui/resizable";

/** The UI the backend declares as its default blok, read when the page connects. */
export function IndexPage() {
  const ui = useBackendUi();
  const blok = ui.status === "ready" ? defaultBlokOf(ui.bloks) : undefined;

  return (
    <div className="h-screen flex flex-col bg-background text-foreground dark">
      {ui.status === "loading" ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          <Loader2 className="size-6 animate-spin" />
        </div>
      ) : blok ? (
        <NewswitchBlok blok={blok} chrome="none" sizing="fill" />
      ) : (
        <>
          {ui.status === "error" && (
            <p className="px-4 py-2 text-xs text-destructive">
              The backend's UI could not be read ({ui.error}); showing the
              built-in one.
            </p>
          )}
          <LegacyIndexLayout />
        </>
      )}
    </div>
  );
}

/** The built-in layout, for a backend that declares no default UI. */
export function LegacyIndexLayout() {
  return (
    <ResizablePanelGroup direction="horizontal" className="flex-1">
      <ResizablePanel defaultSize={15} minSize={10} maxSize={30}>
        <SettingsPanel />
      </ResizablePanel>

      <ResizableHandle withHandle />

      <ResizablePanel defaultSize={55}>
        <div className="h-full flex flex-col overflow-hidden bg-muted/30">
          <Expanse />
        </div>
      </ResizablePanel>

      <ResizableHandle withHandle />

      <ResizablePanel defaultSize={30} minSize={15} maxSize={40}>
        <div className="h-full overflow-y-auto p-4 flex flex-col gap-4">
          <StageControl />
          <MultidimensionalAcquisitionControl />
          <CalibrateLightPath />
          <BloksPanel />
        </div>
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}
