import {
  useActivateDetector,
  useDeactivateDetector,
  useSetWindow,
} from "@/apps/default/hooks/actions";
import {
  useDetectorState,
  type Detector,
} from "@/apps/default/hooks/states/DetectorState";
import { useTuneState } from "@/apps/default/hooks/states/TuneState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Monitor } from "lucide-react";
import { useState } from "react";
import { TuneRow } from "./VariableControl";

type Window = { start: number; size: number };

/**
 * What part of each spatial axis a detector reads, in unbinned steps: of a camera its sensor, of
 * a scan the field (at the same step: a smaller field, not a zoom). Colors and arrival times are
 * always read whole.
 */
function WindowControl({ detector }: { detector: Detector }) {
  const { assign } = useSetWindow();
  const axes = detector.axes.filter(
    (axis) => axis.domain === "space" && axis.size != null,
  );
  const [windows, setWindows] = useState<Record<string, Window>>({});
  if (axes.length === 0) return null;

  const shown = (
    name: string,
    size: number,
    start: number,
    windowSize?: number | null,
  ) => windows[name] ?? { start, size: windowSize ?? size };

  return (
    <div className="space-y-1.5">
      {axes.map((axis) => {
        const value = shown(
          axis.name,
          axis.size ?? 0,
          axis.window_start,
          axis.window_size,
        );
        const set = (change: Partial<Window>) =>
          setWindows((all) => ({
            ...all,
            [axis.name]: { ...value, ...change },
          }));
        return (
          <div key={axis.name} className="flex items-center gap-2 text-xs">
            <span className="w-4 font-mono text-muted-foreground">
              {axis.name}
            </span>
            <Input
              type="number"
              className="h-7 w-20"
              min={0}
              value={value.start}
              onChange={(e) => set({ start: Number(e.target.value) })}
            />
            <span className="text-muted-foreground">+</span>
            <Input
              type="number"
              className="h-7 w-20"
              min={1}
              value={value.size}
              onChange={(e) => set({ size: Number(e.target.value) })}
            />
            <span className="text-muted-foreground">of {axis.size}</span>
          </div>
        );
      })}
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          className="h-7"
          onClick={() =>
            assign({
              name: detector.name,
              windows: axes.map((axis) => ({
                axis: axis.name,
                ...shown(
                  axis.name,
                  axis.size ?? 0,
                  axis.window_start,
                  axis.window_size,
                ),
              })),
            })
          }
        >
          Read this part
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7"
          onClick={() => {
            setWindows({});
            assign({ name: detector.name, windows: [] });
          }}
        >
          All of it
        </Button>
      </div>
    </div>
  );
}

/** What delivers images: each on or off, with whatever it can tune and nothing it can't. */
export function DetectorControl() {
  const { data } = useDetectorState({ subscribe: true });
  const { data: tunes } = useTuneState({ subscribe: true });
  const { assign: activate } = useActivateDetector();
  const { assign: deactivate } = useDeactivateDetector();

  return (
    <div className="space-y-3">
      {data?.detectors.map((detector) => (
        <div key={detector.name} className="space-y-2 rounded-lg border p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Monitor className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">{detector.name}</span>
              <span className="font-mono text-xs text-muted-foreground">
                {detector.axes
                  .map((axis) => `${axis.name} ${axis.delivered_size ?? "…"}`)
                  .join(" × ")}
              </span>
            </div>
            <Switch
              checked={detector.is_active}
              onCheckedChange={(on) =>
                on
                  ? activate({ name: detector.name })
                  : deactivate({ name: detector.name })
              }
            />
          </div>
          {Object.values(tunes?.tunes[detector.name] ?? {}).map((tune) => (
            <TuneRow key={tune.name} variable={tune} />
          ))}
          <WindowControl detector={detector} />
        </div>
      ))}
    </div>
  );
}
