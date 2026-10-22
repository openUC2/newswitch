import { Badge } from "@/components/ui/badge";
import { useCameraState, useStageState } from "@/apps/default/hooks/states";
import { Camera } from "lucide-react";
import { H264_STREAM_PATH } from "@/constants";
import { StreamingView } from "../liveview/StreamingView";

export function LiveView() {
  const { data: cameraState } = useCameraState({ subscribe: true });
  const { data: stageState } = useStageState({ subscribe: true });

  // Use camera state to determine if live view is active
  const isLive = cameraState?.is_acquiring ?? false;
  // The H.264 stream of the first active detector (the backend's /stream/h264/<slot>).
  const slot =
    cameraState?.detectors.find((detector) => detector.is_active)?.slot ?? 1;

  return (
    <div className="flex flex-col h-full bg-black rounded-lg overflow-hidden">
      {/* Image viewport */}
      <div className="relative flex-1 overflow-hidden">
        {/* StreamingView or placeholder */}
        {isLive ? (
          <div className="absolute inset-0">
            <StreamingView url={`${H264_STREAM_PATH}/${slot}`} />
          </div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-zinc-600 text-sm flex flex-col items-center gap-2">
              <Camera className="h-12 w-12 text-zinc-700" />
              Press Live to start
            </div>
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
          {cameraState && (
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
