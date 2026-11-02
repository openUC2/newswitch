import {
  useActivateDetector,
  useDeactivateDetector,
} from "@/apps/default/hooks/actions";
import { useDetectorState } from "@/apps/default/hooks/states/DetectorState";
import { useTuneState } from "@/apps/default/hooks/states/TuneState";
import { Switch } from "@/components/ui/switch";
import { Monitor } from "lucide-react";
import { TuneRow } from "./VariableControl";

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
        </div>
      ))}
    </div>
  );
}
