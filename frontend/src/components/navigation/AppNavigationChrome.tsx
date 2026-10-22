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
import { Activity, History, Loader2, PlaySquare } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { buttonVariants } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { AccountMenu } from "./AccountMenu";
import { BottomBarSlotContext } from "./bottomBar";
import { useAppStateContext } from "@/lib/arkitekt/app-state/app-state-context";
import {
  selectLatestPatches,
  useGlobalStateStore,
} from "@/lib/arkitekt/state/store";
import { useStateContext } from "@/lib/arkitekt/state";
import { useTransport } from "@/lib/arkitekt/transport";
import type { AppKey } from "@/lib/arkitekt/types";
import type { JournalBounds } from "@/lib/arkitekt/transport/types";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";

const DEBOUNCE_MS = 220;
const TIMELINE_CHANGE_LIMIT = 8;

type OverlayMode = "live" | "timeline";

/** The span of an app's current journal session. */
type AppTimelineBoundary = {
  appKey: AppKey;
  sessionId: string;
  startMs: number;
  endMs: number;
  endPos: number;
};

const navigationItems = [
  {
    to: "/",
    labelKey: "navigation.index",
    icon: Activity,
  },
  {
    to: "/replay",
    labelKey: "navigation.replay",
    icon: PlaySquare,
  },
] as const;

const formatTimelineLabel = (ms: number, locale?: string) =>
  new Date(ms).toLocaleString(locale, {
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
  const { t } = useTranslation();
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
        <span className="text-muted-foreground">
          {t("navigation.latestChanges")}
        </span>
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

async function fetchTimelineBoundaries(
  appKeys: AppKey[],
  fetchJournalBounds: (appKey: AppKey) => Promise<JournalBounds>,
): Promise<AppTimelineBoundary[]> {
  return Promise.all(
    appKeys.map(async (appKey) => {
      const bounds = await fetchJournalBounds(appKey);

      return {
        appKey,
        sessionId: bounds.sessionId,
        startMs: bounds.start.getTime(),
        endMs: bounds.end.getTime(),
        endPos: bounds.endPos,
      } satisfies AppTimelineBoundary;
    }),
  );
}

function resetTimelineState(
  setMode: (mode: OverlayMode) => void,
  setBoundaries: (boundaries: AppTimelineBoundary[]) => void,
  setSelectedMs: (value: number | null) => void,
  setDebouncedSelectedMs: (value: number | null) => void,
  lastCheckoutMsRef: MutableRefObject<number | null>,
  setShownPositions: (positions: Partial<Record<AppKey, number>>) => void,
) {
  lastCheckoutMsRef.current = null;
  setShownPositions({});
  setMode("live");
  setBoundaries([]);
  setSelectedMs(null);
  setDebouncedSelectedMs(null);
}

// TODO: not mounted (see AppLatestChanges above).
export function RouteNavigationBar() {
  const { t } = useTranslation();
  return (
    <div className="pointer-events-none fixed top-1/2 left-4 z-50 -translate-y-1/2">
      <div className="pointer-events-auto flex flex-col gap-2 rounded-2xl border border-border bg-background/85 p-2 shadow-lg backdrop-blur-sm dark">
        {navigationItems.map(({ to, labelKey, icon: Icon }) => (
          <Tooltip key={to}>
            <TooltipTrigger asChild>
              <NavLink
                to={to}
                end={to === "/"}
                aria-label={t(labelKey)}
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
              {t(labelKey)}
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
    </div>
  );
}

function TimelineFloater() {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const appStateContext = useAppStateContext();
  const transport = useTransport();
  const stateContext = useStateContext();
  const { fetchJournalBounds } = transport;

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
  const lastCheckoutMsRef = useRef<number | null>(null);
  const [shownPositions, setShownPositions] = useState<
    Partial<Record<AppKey, number>>
  >({});
  const checkoutRef = useRef(stateContext.checkoutAt);
  const previousIsReplayRouteRef = useRef(false);
  const isReplayRoute = location.pathname === "/replay";

  useEffect(() => {
    checkoutRef.current = stateContext.checkoutAt;
  }, [stateContext.checkoutAt]);

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
    if (mode !== "timeline") {
      return [] as Array<{ appKey: AppKey; revision: number }>;
    }

    return boundaries.flatMap((boundary) => {
      const pos = shownPositions[boundary.appKey];
      return pos == null ? [] : [{ appKey: boundary.appKey, revision: pos }];
    });
  }, [boundaries, mode, shownPositions]);

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
        fetchJournalBounds,
      );

      if (nextBoundaries.length === 0) {
        throw new Error(t("navigation.noTimeline"));
      }

      const timelineEndMs = Math.max(
        ...nextBoundaries.map((boundary) => boundary.endMs),
      );

      lastCheckoutMsRef.current = null;
      setShownPositions({});
      setBoundaries(nextBoundaries);
      setSelectedMs(timelineEndMs);
      setDebouncedSelectedMs(timelineEndMs);
      setMode("timeline");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("navigation.timelineFailed");
      toast.error(message);
      void goLiveAll();
      setMode("live");
    } finally {
      setIsPreparingTimeline(false);
    }
  }, [appKeys, fetchJournalBounds, goLiveAll, stopLiveAll, t]);

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
        lastCheckoutMsRef,
        setShownPositions,
      );
      await goLiveAll();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("navigation.liveFailed");
      toast.error(message);
    } finally {
      setIsReturningToLive(false);
    }
  }, [goLiveAll, t]);

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
        if (lastCheckoutMsRef.current === debouncedSelectedMs) {
          return;
        }
        lastCheckoutMsRef.current = debouncedSelectedMs;

        const positions = await Promise.all(
          boundaries.map(async (boundary) => {
            const at = new Date(
              clamp(debouncedSelectedMs, boundary.startMs, boundary.endMs),
            );
            const pos = await checkoutRef.current(boundary.appKey, at);
            return [boundary.appKey, pos] as const;
          }),
        );
        if (!cancelled) {
          setShownPositions(Object.fromEntries(positions));
        }
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : t("navigation.checkoutFailed");
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
  }, [boundaries, debouncedSelectedMs, mode, t]);

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
    <>
      {/* The past is unmistakable: an amber frame around the whole screen. */}
      <AnimatePresence>
        {mode === "timeline" ? (
          <motion.div
            key="past-frame"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-none fixed inset-0 z-40 rounded-[inherit] ring-2 ring-inset ring-amber-400/50"
          />
        ) : null}
      </AnimatePresence>

      {/* The timeline floats just above the bottom bar while replaying. */}
      <div className="pointer-events-none fixed inset-x-4 bottom-16 z-50 flex justify-end">
        <AnimatePresence initial={false}>
          {mode === "timeline" && timelineBounds && selectedMs != null ? (
            <motion.div
              key="timeline-expanded"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 12 }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              className="dark pointer-events-auto w-full max-w-4xl overflow-hidden rounded-2xl border border-amber-400/40 bg-background/90 shadow-2xl backdrop-blur-xl"
            >
              <div className="flex min-w-0 flex-col gap-2 px-4 py-2.5">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="flex items-center gap-1.5 rounded-full bg-amber-400/15 px-2 py-0.5 text-[11px] font-semibold text-amber-300">
                      <History className="size-3" />
                      {t("navigation.viewingPast")}
                    </span>
                    <span className="truncate text-sm font-medium tabular-nums text-foreground">
                      {formatTimelineLabel(selectedMs, i18n.resolvedLanguage)}
                    </span>
                    {isCheckingOut ? (
                      <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" />
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5 text-[11px] text-muted-foreground">
                    {selectedRevisions.map(({ appKey, revision }) => (
                      <span
                        key={`${appKey}:${revision}`}
                        className="rounded-md border border-border/60 px-1.5 py-0.5 font-mono"
                        title={appKey}
                      >
                        {t("navigation.revision")} {revision}
                      </span>
                    ))}
                  </div>
                </div>

                <Slider
                  value={sliderValue}
                  onValueChange={onSliderChange}
                  min={0}
                  max={100}
                  step={0.1}
                  className="w-full [&_[data-slot=slider-range]]:bg-amber-400 [&_[data-slot=slider-thumb]]:size-4 [&_[data-slot=slider-thumb]]:border-amber-400 [&_[data-slot=slider-track]]:h-1.5"
                  aria-label={t("navigation.timelinePosition")}
                />

                <div className="flex justify-between text-[11px] text-muted-foreground tabular-nums">
                  <span>
                    {t("navigation.sessionStart")} ·{" "}
                    {formatTimelineLabel(
                      timelineBounds.startMs,
                      i18n.resolvedLanguage,
                    )}
                  </span>
                  <span>{t("navigation.pastPaused")}</span>
                  <span>
                    {formatTimelineLabel(
                      timelineBounds.endMs,
                      i18n.resolvedLanguage,
                    )}
                  </span>
                </div>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

      <ModeSwitch
        mode={mode}
        busy={isPreparingTimeline || isReturningToLive}
        onLive={() => {
          if (mode === "timeline") void returnToLive();
        }}
        onReplay={() => {
          if (mode !== "timeline") void loadTimeline();
        }}
      />
    </>
  );
}

/** Live or replay: a two-way switch whose highlight slides to the active side. */
function ModeSwitch({
  mode,
  busy,
  onLive,
  onReplay,
}: {
  mode: OverlayMode;
  busy: boolean;
  onLive: () => void;
  onReplay: () => void;
}) {
  const { t } = useTranslation();
  const segments = [
    {
      key: "live" as const,
      label: t("navigation.live"),
      hint: t("navigation.liveHint"),
      onClick: onLive,
      icon: (
        <span className="relative flex size-2">
          {mode === "live" ? (
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          ) : null}
          <span
            className={cn(
              "relative inline-flex size-2 rounded-full",
              mode === "live" ? "bg-emerald-400" : "bg-muted-foreground/60",
            )}
          />
        </span>
      ),
    },
    {
      key: "timeline" as const,
      label: t("navigation.replay"),
      hint: t("navigation.replayHint"),
      onClick: onReplay,
      icon:
        busy && mode === "live" ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <History className="size-3.5" />
        ),
    },
  ];

  return (
    <div
      role="radiogroup"
      aria-label={t("navigation.timelinePosition")}
      className="relative flex shrink-0 items-center rounded-full bg-muted/50 p-0.5"
    >
      {segments.map((segment) => {
        const active = mode === segment.key;
        return (
          <Tooltip key={segment.key}>
            <TooltipTrigger asChild>
              <button
                type="button"
                role="radio"
                aria-checked={active}
                disabled={busy || active}
                onClick={segment.onClick}
                className={cn(
                  "relative flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-default",
                  active
                    ? segment.key === "live"
                      ? "text-emerald-50"
                      : "text-amber-50"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {active ? (
                  <motion.span
                    layoutId="mode-switch-highlight"
                    transition={{ type: "spring", stiffness: 400, damping: 32 }}
                    className={cn(
                      "absolute inset-0 rounded-full",
                      segment.key === "live"
                        ? "bg-emerald-600/80"
                        : "bg-amber-600/80",
                    )}
                  />
                ) : null}
                <span className="relative flex items-center gap-1.5">
                  {segment.icon}
                  {segment.label}
                </span>
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" sideOffset={8}>
              {segment.hint}
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}

/**
 * The microscope pages: the page above, one bar at the bottom. The bar holds what the
 * page puts in it (its views), the live/replay switch, the language and the account.
 */
export function AppNavigationChrome({ children }: { children: ReactNode }) {
  const [slot, setSlot] = useState<ReactNode | null>(null);

  return (
    <BottomBarSlotContext.Provider value={setSlot}>
      <div className="dark flex h-screen flex-col bg-background text-foreground">
        <div className="relative min-h-0 flex-1">{children}</div>
        <nav
          aria-label="Bottom bar"
          className="flex h-14 shrink-0 items-center gap-2 border-t border-border/60 bg-background/95 px-3 backdrop-blur"
        >
          <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
            {slot}
          </div>
          <TimelineFloater />
          <div className="h-6 w-px bg-border/60" />
          <AccountMenu placement="inline" />
        </nav>
      </div>
    </BottomBarSlotContext.Provider>
  );
}
