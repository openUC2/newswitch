import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, History, Loader2, PlaySquare, Radio } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { buttonVariants, Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { AccountMenu } from "./AccountMenu";
import { useAppStateContext } from "@/lib/rekuest/app-state/app-state-context";
import {
  selectLatestPatches,
  useGlobalStateStore,
} from "@/lib/rekuest/state/store";
import { useStateContext } from "@/lib/rekuest/state";
import { useTransport } from "@/lib/rekuest/transport";
import type { AppKey } from "@/lib/rekuest/types";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 220;
const TIMELINE_CHANGE_LIMIT = 8;

type OverlayMode = "live" | "timeline";

type AppTimelineBoundary = {
  appKey: AppKey;
  sessionId: string;
  startMs: number;
  endMs: number;
  startRevision: number;
  endRevision: number;
};

const navigationItems = [
  {
    to: "/",
    label: "Index",
    icon: Activity,
  },
  {
    to: "/replay",
    label: "Replay",
    icon: PlaySquare,
  },
] as const;

const formatTimelineLabel = (ms: number) =>
  new Date(ms).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

const formatPatchPath = (path: string) => {
  if (!path) {
    return "state";
  }

  const normalizedPath = path.startsWith("/") ? path.slice(1) : path;
  return normalizedPath || "state";
};

type AppLatestChangesProps = {
  appKey: AppKey;
};

// TODO: not mounted. AppNavigationChrome renders only <TimelineFloater />, so this - the
// only consumer of latestPatches - never appears, even though the README describes recent
// patches as being surfaced in the nav chrome. Exported rather than deleted: it is
// unfinished wiring, not dead code.
export function AppLatestChanges({ appKey }: AppLatestChangesProps) {
  const latestPatches = useGlobalStateStore(
    appKey,
    selectLatestPatches(TIMELINE_CHANGE_LIMIT),
  );

  const recentChanges = useMemo(() => {
    const seen = new Set<string>();

    return [...latestPatches]
      .reverse()
      .filter((patch) => {
        const identity = `${patch.stateName}:${patch.path}:${patch.revision}`;

        if (seen.has(identity)) {
          return false;
        }

        seen.add(identity);
        return true;
      })
      .slice(0, 4);
  }, [latestPatches]);

  if (recentChanges.length === 0) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-border/50 bg-muted/25 p-3">
      <div className="mb-2 flex items-center justify-between gap-2 text-xs">
        <span className="font-semibold text-foreground">{appKey}</span>
        <span className="text-muted-foreground">Latest changes</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {recentChanges.map((patch, index) => (
          <div
            key={`${patch.stateName}:${patch.path}:${patch.revision}:${index}`}
            className="rounded-full border border-border/50 bg-background/70 px-2.5 py-1 text-[11px]"
          >
            <span className="font-medium text-foreground">
              {patch.stateName}
            </span>
            <span className="mx-1 text-muted-foreground">/</span>
            <span className="font-mono text-muted-foreground">
              {formatPatchPath(patch.path)}
            </span>
            <span className="mx-1 text-muted-foreground">@</span>
            <span className="font-mono text-foreground">{patch.revision}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

const toPercent = (value: number, min: number, max: number) => {
  if (max <= min) {
    return 100;
  }

  return ((value - min) / (max - min)) * 100;
};

const fromPercent = (percent: number, min: number, max: number) => {
  if (max <= min) {
    return max;
  }

  return min + ((max - min) * percent) / 100;
};

const toRevisionAtTime = (boundary: AppTimelineBoundary, targetMs: number) => {
  const clampedMs = clamp(targetMs, boundary.startMs, boundary.endMs);

  if (boundary.endMs <= boundary.startMs) {
    return boundary.endRevision;
  }

  const progress =
    (clampedMs - boundary.startMs) / (boundary.endMs - boundary.startMs);

  return Math.round(
    boundary.startRevision +
      progress * (boundary.endRevision - boundary.startRevision),
  );
};

async function fetchTimelineBoundaries(
  appKeys: AppKey[],
  fetchActiveSessionBoundaries: (appKey: AppKey) => Promise<{
    sessionId: string;
    sessionStart: Date;
    sessionEnd: Date;
    startRevision: number;
    endRevision: number;
  }>,
): Promise<AppTimelineBoundary[]> {
  return Promise.all(
    appKeys.map(async (appKey) => {
      const session = await fetchActiveSessionBoundaries(appKey);

      return {
        appKey,
        sessionId: session.sessionId,
        startMs: session.sessionStart.getTime(),
        endMs: session.sessionEnd.getTime(),
        startRevision: session.startRevision,
        endRevision: session.endRevision,
      } satisfies AppTimelineBoundary;
    }),
  );
}

function resetTimelineState(
  setMode: (mode: OverlayMode) => void,
  setBoundaries: (boundaries: AppTimelineBoundary[]) => void,
  setSelectedMs: (value: number | null) => void,
  setDebouncedSelectedMs: (value: number | null) => void,
  lastCheckoutRevisionRef: MutableRefObject<Partial<Record<AppKey, number>>>,
) {
  lastCheckoutRevisionRef.current = {};
  setMode("live");
  setBoundaries([]);
  setSelectedMs(null);
  setDebouncedSelectedMs(null);
}

// TODO: not mounted (see AppLatestChanges above).
export function RouteNavigationBar() {
  return (
    <div className="pointer-events-none fixed top-1/2 left-4 z-50 -translate-y-1/2">
      <div className="pointer-events-auto flex flex-col gap-2 rounded-2xl border border-border bg-background/85 p-2 shadow-lg backdrop-blur-sm dark">
        {navigationItems.map(({ to, label, icon: Icon }) => (
          <Tooltip key={to}>
            <TooltipTrigger asChild>
              <NavLink
                to={to}
                end={to === "/"}
                aria-label={label}
                className={({ isActive }) =>
                  cn(
                    buttonVariants({
                      variant: isActive ? "default" : "ghost",
                      size: "icon",
                    }),
                    "rounded-xl",
                  )
                }
              >
                <Icon className="size-4" />
              </NavLink>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={10}>
              {label}
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
    </div>
  );
}

function TimelineFloater() {
  const location = useLocation();
  const appStateContext = useAppStateContext();
  const transport = useTransport();
  const stateContext = useStateContext();
  const { fetchActiveSessionBoundaries } = transport;

  const appKeys = useMemo(
    () => Object.keys(transport.apps) as AppKey[],
    [transport.apps],
  );

  const [mode, setMode] = useState<OverlayMode>("live");
  const [boundaries, setBoundaries] = useState<AppTimelineBoundary[]>([]);
  const [selectedMs, setSelectedMs] = useState<number | null>(null);
  const [debouncedSelectedMs, setDebouncedSelectedMs] = useState<number | null>(
    null,
  );
  const [isPreparingTimeline, setIsPreparingTimeline] = useState(false);
  const [isCheckingOut, setIsCheckingOut] = useState(false);
  const [isReturningToLive, setIsReturningToLive] = useState(false);
  const lastCheckoutRevisionRef = useRef<Partial<Record<AppKey, number>>>({});
  const checkoutRef = useRef(stateContext.checkout);
  const previousIsReplayRouteRef = useRef(false);
  const isReplayRoute = location.pathname === "/replay";

  useEffect(() => {
    checkoutRef.current = stateContext.checkout;
  }, [stateContext.checkout]);

  const goLiveAll = useCallback(async () => {
    await Promise.all(
      appKeys.map(async (appKey) => {
        await appStateContext.goLive(appKey);
      }),
    );
  }, [appKeys, appStateContext]);

  const stopLiveAll = useCallback(async () => {
    await Promise.all(
      appKeys.map(async (appKey) => {
        await appStateContext.stopLive(appKey);
      }),
    );
  }, [appKeys, appStateContext]);

  const timelineBounds = useMemo(() => {
    if (boundaries.length === 0) {
      return null;
    }

    return {
      startMs: Math.min(...boundaries.map((boundary) => boundary.startMs)),
      endMs: Math.max(...boundaries.map((boundary) => boundary.endMs)),
    };
  }, [boundaries]);

  const sliderValue = useMemo<[number]>(() => {
    if (!timelineBounds || selectedMs == null) {
      return [100];
    }

    return [
      toPercent(selectedMs, timelineBounds.startMs, timelineBounds.endMs),
    ];
  }, [selectedMs, timelineBounds]);

  const selectedRevisions = useMemo(() => {
    if (mode !== "timeline" || selectedMs == null) {
      return [] as Array<{ appKey: AppKey; revision: number }>;
    }

    return boundaries.map((boundary) => ({
      appKey: boundary.appKey,
      revision: toRevisionAtTime(boundary, selectedMs),
    }));
  }, [boundaries, mode, selectedMs]);

  useEffect(() => {
    if (appKeys.length === 0) {
      return;
    }

    void goLiveAll();

    return () => {
      void stopLiveAll();
    };
  }, [appKeys.length, goLiveAll, stopLiveAll]);

  useEffect(() => {
    if (mode !== "timeline" || selectedMs == null) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setDebouncedSelectedMs(selectedMs);
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [mode, selectedMs]);

  const loadTimeline = useCallback(async () => {
    setIsPreparingTimeline(true);

    try {
      await stopLiveAll();

      const nextBoundaries = await fetchTimelineBoundaries(
        appKeys,
        fetchActiveSessionBoundaries,
      );

      if (nextBoundaries.length === 0) {
        throw new Error("No active session boundaries were available.");
      }

      const timelineEndMs = Math.max(
        ...nextBoundaries.map((boundary) => boundary.endMs),
      );

      lastCheckoutRevisionRef.current = {};
      setBoundaries(nextBoundaries);
      setSelectedMs(timelineEndMs);
      setDebouncedSelectedMs(timelineEndMs);
      setMode("timeline");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to prepare timeline";
      toast.error(message);
      void goLiveAll();
      setMode("live");
    } finally {
      setIsPreparingTimeline(false);
    }
  }, [appKeys, fetchActiveSessionBoundaries, goLiveAll, stopLiveAll]);

  useEffect(() => {
    const wasReplayRoute = previousIsReplayRouteRef.current;
    previousIsReplayRouteRef.current = isReplayRoute;

    if (!isReplayRoute || wasReplayRoute) {
      return;
    }

    void loadTimeline();
  }, [isReplayRoute, loadTimeline]);

  const returnToLive = useCallback(async () => {
    setIsReturningToLive(true);

    try {
      resetTimelineState(
        setMode,
        setBoundaries,
        setSelectedMs,
        setDebouncedSelectedMs,
        lastCheckoutRevisionRef,
      );
      await goLiveAll();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to return to live mode";
      toast.error(message);
    } finally {
      setIsReturningToLive(false);
    }
  }, [goLiveAll]);

  useEffect(() => {
    if (
      mode !== "timeline" ||
      debouncedSelectedMs == null ||
      boundaries.length === 0
    ) {
      return;
    }

    let cancelled = false;

    const checkoutAtTime = async () => {
      setIsCheckingOut(true);

      try {
        await Promise.all(
          boundaries.map(async (boundary) => {
            const nextRevision = toRevisionAtTime(
              boundary,
              debouncedSelectedMs,
            );

            if (
              lastCheckoutRevisionRef.current[boundary.appKey] === nextRevision
            ) {
              return;
            }

            lastCheckoutRevisionRef.current[boundary.appKey] = nextRevision;

            await checkoutRef.current(boundary.appKey, nextRevision, {
              appKey: boundary.appKey,
            });
          }),
        );
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Failed to checkout timeline state";
        toast.error(message);
      } finally {
        if (!cancelled) {
          setIsCheckingOut(false);
        }
      }
    };

    void checkoutAtTime();

    return () => {
      cancelled = true;
    };
  }, [boundaries, debouncedSelectedMs, mode]);

  const onSliderChange = useCallback(
    (value: number[]) => {
      if (!timelineBounds) {
        return;
      }

      const nextMs = fromPercent(
        value[0] ?? 100,
        timelineBounds.startMs,
        timelineBounds.endMs,
      );

      setSelectedMs(Math.round(nextMs));
    },
    [timelineBounds],
  );

  return (
    <div className="pointer-events-none fixed inset-x-4 bottom-4  z-50 flex justify-end">
      <motion.div
        layout
        transition={{ type: "spring", stiffness: 220, damping: 26 }}
        className={cn(
          "pointer-events-auto overflow-hidden border border-border/60 bg-background/90 shadow-2xl backdrop-blur-xl dark flex-row-reverse flex items-center gap-4 p-3 rounded-full",
          mode === "timeline" ? "w-full rounded-3xl" : "w-auto rounded-full",
        )}
      >
        <div className="flex items-center gap-2 p-2 w-full">
          <Button
            size="icon"
            variant={mode === "live" ? "default" : "outline"}
            onClick={() => {
              if (mode === "timeline") {
                void returnToLive();
              }
            }}
            disabled={mode === "live" || isReturningToLive}
          >
            <Radio className="mr-2 size-4" />
          </Button>

          <Button
            size="icon"
            variant={mode === "timeline" ? "default" : "outline"}
            onClick={() => {
              if (mode !== "timeline") {
                void loadTimeline();
              }
            }}
            disabled={mode === "timeline" || isPreparingTimeline}
          >
            {isPreparingTimeline ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <History className="mr-2 size-4" />
            )}
          </Button>

          <AnimatePresence initial={false}>
            {mode === "timeline" && timelineBounds && selectedMs != null ? (
              <motion.div
                key="timeline-expanded"
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: "100%" }}
                exit={{ opacity: 0, width: 0 }}
                transition={{ type: "spring", stiffness: 220, damping: 28 }}
                className="@container min-w-0 flex-1"
              >
                <div className="flex min-w-0 flex-col gap-3 px-3 py-2">
                  <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
                    <div className="font-medium">
                      {formatTimelineLabel(timelineBounds.startMs)}
                    </div>
                    <div className="flex items-center gap-2 rounded-full border border-border/60 bg-background/70 px-3 py-1 text-foreground">
                      {isCheckingOut ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : null}
                      <span>{formatTimelineLabel(selectedMs)}</span>
                    </div>
                    <div className="font-medium">
                      {formatTimelineLabel(timelineBounds.endMs)}
                    </div>
                  </div>

                  <div className="flex flex-wrap justify-center gap-2 text-[11px] text-muted-foreground">
                    {selectedRevisions.map(({ appKey, revision }) => (
                      <div
                        key={`${appKey}:${revision}`}
                        className="rounded-full border border-border/50 bg-muted/30 px-2.5 py-1"
                      >
                        <span className="font-semibold text-foreground">
                          {appKey}
                        </span>
                        <span className="mx-1">rev</span>
                        <span className="font-mono text-foreground">
                          {revision}
                        </span>
                      </div>
                    ))}
                  </div>

                  <Slider
                    value={sliderValue}
                    onValueChange={onSliderChange}
                    min={0}
                    max={100}
                    step={0.1}
                    className="w-full [&_[data-slot=slider-thumb]]:size-5 [&_[data-slot=slider-track]]:h-2"
                    aria-label="Timeline position"
                  />

                  <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                    {boundaries.map((boundary) => (
                      <div
                        key={`${boundary.appKey}:${boundary.sessionId}`}
                        className="rounded-full border border-border/50 bg-muted/40 px-2.5 py-1"
                      >
                        <span className="font-semibold text-foreground">
                          {boundary.appKey}
                        </span>
                        <span className="mx-1">•</span>
                        <span>{formatTimelineLabel(boundary.startMs)}</span>
                        <span className="mx-1">→</span>
                        <span>{formatTimelineLabel(boundary.endMs)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </div>
      </motion.div>
    </div>
  );
}

export function AppNavigationChrome({ children }: { children: ReactNode }) {
  return (
    <>
      <TimelineFloater />
      <AccountMenu />
      {children}
    </>
  );
}
