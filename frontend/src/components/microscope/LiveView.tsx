import { Badge } from "@/components/ui/badge";
import { useDetectorState } from "@/apps/default/hooks/states";
import { deliversImages } from "@/lib/microscope/space";
import { useStagePosition } from "@/lib/microscope/values";
import { Camera } from "lucide-react";
import { useState } from "react";
import { StreamingView } from "../liveview/StreamingView";

export function LiveView({ detector: named }: { detector?: string }) {
  const { data: detectorState } = useDetectorState({ subscribe: true });
  const stageState = useStagePosition();

  // Use camera state to determine if live view is active
  const isLive = detectorState?.is_acquiring ?? false;
  // The one it is told to show, or the one picked, or else the first that is on.
  const active =
    detectorState?.detectors.filter((d) => d.is_active && deliversImages(d)) ??
    [];
  const [picked, setPicked] = useState<string | null>(null);
  const detector =
    named ?? active.find((d) => d.name === picked)?.name ?? active.at(0)?.name;

  return (
    <div className="flex flex-col h-full bg-black rounded-lg overflow-hidden">
      {/* Image viewport */}
      <div className="relative flex-1 overflow-hidden">
        {/* StreamingView or placeholder */}
        {isLive && detector ? (
          <div className="absolute inset-0">
            <StreamingView detector={detector} />
          </div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-zinc-600 text-sm flex flex-col items-center gap-2">
              <Camera className="h-12 w-12 text-zinc-700" />
              Press Live to start
            </div>
          </div>
        )}

        {isLive && detector && !named && active.length > 1 && (
          <div className="absolute left-1/2 top-2 z-10 flex -translate-x-1/2 gap-1 rounded-full bg-black/60 p-1">
            {active.map((d) => (
              <button
                key={d.name}
                type="button"
                className={
                  d.name === detector
                    ? "rounded-full bg-white/20 px-2 py-0.5 text-[11px] text-white"
                    : "rounded-full px-2 py-0.5 text-[11px] text-white/60"
                }
                onClick={() => setPicked(d.name)}
              >
                {d.name}
              </button>
            ))}
          </div>
        )}

        {/* Status badges */}
        <div className="absolute top-2 left-2 flex flex-col gap-1">
          {isLive && (
            <Badge variant="destructive" className="gap-1">
              <span className="h-2 w-2 rounded-full bg-white animate-pulse" />
              LIVE
            </Badge>
          )}
          {detectorState && (
            <Badge variant="secondary" className="text-xs"></Badge>
          )}
        </div>

        {/* Stage position */}
        <div className="absolute bottom-2 left-2 flex gap-2">
          {stageState && (
            <Badge variant="outline" className="text-xs font-mono bg-black/50">
              X: {stageState.x?.toFixed(1)} Y: {stageState.y?.toFixed(1)} Z:{" "}
              {stageState.z?.toFixed(1)}
            </Badge>
          )}
        </div>
      </div>
    </div>
  );
}
