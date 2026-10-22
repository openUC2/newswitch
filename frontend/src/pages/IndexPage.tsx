import { bloks, type BlokKey } from "@/apps/default/bloks";
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

/** The panel the backend declares as its default UI (`nsapp.blok(..., default=True)`). */
const defaultBlokKey = (Object.keys(bloks) as BlokKey[]).find((key) => {
  const blok = bloks[key] as { default?: boolean; context?: string };
  return blok.default === true && blok.context === "HTML";
});

export function IndexPage() {
  return (
    <div className="h-screen flex flex-col bg-background text-foreground dark">
      {defaultBlokKey ? (
        <NewswitchBlok blokKey={defaultBlokKey} chrome="none" sizing="fill" />
      ) : (
        <LegacyIndexLayout />
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
