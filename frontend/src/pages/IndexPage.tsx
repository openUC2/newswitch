import { useCallback, useMemo, useState } from "react";
import { useBottomBarSlot } from "@/components/navigation/bottomBar";
import { motion } from "framer-motion";
import {
  Box,
  LayoutDashboard,
  Loader2,
  Move3d,
  Video,
  type LucideIcon,
} from "lucide-react";
import {
  defaultBlokOf,
  useBackendUi,
  viewsOf,
  type BackendView,
} from "@/lib/blok/backendUi";
import { cn } from "@/lib/utils";
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

/** Where the chosen view is remembered (per browser). */
const VIEW_STORAGE_KEY = "newswitch.view";

const readStoredView = (): string | null => {
  try {
    return window.localStorage.getItem(VIEW_STORAGE_KEY);
  } catch {
    return null;
  }
};

const storeView = (key: string) => {
  try {
    window.localStorage.setItem(VIEW_STORAGE_KEY, key);
  } catch {
    // Not remembered; the backend's default is shown next time.
  }
};

/**
 * The UI the backend declares, read when the page connects: its views, the one
 * chosen (remembered, else the backend's default) filling the page, and a bar at
 * the bottom to switch between them when there is more than one.
 */
export function IndexPage() {
  const ui = useBackendUi();
  const [chosen, setChosen] = useState<string | null>(readStoredView);

  const views = ui.status === "ready" ? viewsOf(ui.bloks) : [];
  const fallback = ui.status === "ready" ? defaultBlokOf(ui.bloks) : undefined;
  const current =
    views.find((view) => view.key === chosen)?.blok ??
    fallback ??
    views[0]?.blok;
  const showBar = views.length > 1;

  // The view tabs go on the left of the bottom bar.
  const choose = useCallback((key: string) => {
    setChosen(key);
    storeView(key);
  }, []);
  const tabs = useMemo(
    () =>
      showBar && current ? (
        <ViewBar views={views} current={current.key} onChoose={choose} />
      ) : null,
    // `views` is rebuilt every render; its keys say whether the tabs changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [showBar, current?.key, views.map((view) => view.key).join(","), choose],
  );
  useBottomBarSlot(tabs);

  return (
    <div className="flex h-full flex-col bg-background text-foreground dark">
      {ui.status === "loading" ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          <Loader2 className="size-6 animate-spin" />
        </div>
      ) : current ? (
        <>
          <div className="relative min-h-0 flex-1">
            <NewswitchBlok
              key={current.key}
              blok={current}
              chrome="none"
              sizing="fill"
            />
          </div>
        </>
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

const VIEW_ICONS: Record<string, LucideIcon> = {
  "view-3d": Box,
  "view-stage": Move3d,
  "view-minimal": Video,
  "view-standard": LayoutDashboard,
};

/** The view tabs in the bottom bar: one per view the backend declares. */
function ViewBar({
  views,
  current,
  onChoose,
}: {
  views: BackendView[];
  current: string;
  onChoose: (key: string) => void;
}) {
  return (
    <div role="tablist" aria-label="Views" className="flex items-center gap-1">
      {views.map((view) => {
        const Icon = VIEW_ICONS[view.key] ?? LayoutDashboard;
        const active = view.key === current;
        return (
          <button
            key={view.key}
            type="button"
            role="tab"
            aria-selected={active}
            title={view.blok.description ?? view.label}
            onClick={() => onChoose(view.key)}
            className={cn(
              "relative flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "text-foreground"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
            )}
          >
            {active ? (
              <motion.span
                layoutId="view-bar-highlight"
                transition={{ type: "spring", stiffness: 400, damping: 34 }}
                className="absolute inset-0 rounded-lg bg-muted"
              />
            ) : null}
            <span className="relative flex items-center gap-2">
              <Icon className="size-4" />
              {view.label}
            </span>
          </button>
        );
      })}
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
