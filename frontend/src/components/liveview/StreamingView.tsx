import React, { useEffect, useRef, useState } from "react";
import { frameToRgba, type LiveFrame } from "./frames";
import { DEFAULT_MAX_SIZE, FULL_SIZE, useFrameStream } from "./frameStream";

interface StreamingViewProps {
  /** The detector to show */
  slot: number;
  /** Custom class name for container */
  className?: string;
}

const STATE_COLORS = {
  live: "bg-green-500",
  connecting: "bg-yellow-500 animate-pulse",
  disconnected: "bg-gray-500",
};

export const StreamingView: React.FC<StreamingViewProps> = ({
  slot,
  className,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const latestRef = useRef<LiveFrame | null>(null);
  const [fullSize, setFullSize] = useState(false);
  const [size, setSize] = useState<[number, number] | null>(null);

  const state = useFrameStream(
    slot,
    fullSize ? FULL_SIZE : DEFAULT_MAX_SIZE,
    (frame) => {
      latestRef.current = frame;
    },
  );

  // Draws the newest frame once per screen refresh, whatever came in between.
  useEffect(() => {
    let drawn: LiveFrame | null = null;
    let request = requestAnimationFrame(function draw() {
      request = requestAnimationFrame(draw);
      const frame = latestRef.current;
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!frame || frame === drawn || !canvas || !context) return;
      drawn = frame;
      if (canvas.width !== frame.width || canvas.height !== frame.height) {
        canvas.width = frame.width;
        canvas.height = frame.height;
        setSize([frame.width, frame.height]);
      }
      context.putImageData(
        new ImageData(frameToRgba(frame), frame.width, frame.height),
        0,
        0,
      );
    });
    return () => cancelAnimationFrame(request);
  }, []);

  return (
    <div className={`relative w-full h-full ${className || ""}`}>
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full object-contain bg-black"
      />

      <div className="absolute top-2 right-2 flex items-center gap-2 text-xs bg-black/60 px-2 py-1 rounded">
        <div className={`w-2 h-2 rounded-full ${STATE_COLORS[state]}`} />
        <span className="text-white/80 capitalize">{state}</span>
        {state === "live" && size && (
          <span className="text-white/50">
            {size[0]}×{size[1]}
          </span>
        )}
        <button
          onClick={() => setFullSize((value) => !value)}
          className="text-white/80 underline-offset-2 hover:underline"
        >
          {fullSize ? "Binned" : "Full size"}
        </button>
      </div>

      {state !== "live" && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/70">
          <span className="text-white text-sm">
            {state === "connecting"
              ? "Waiting for frames..."
              : "Disconnected, reconnecting..."}
          </span>
        </div>
      )}
    </div>
  );
};

export default StreamingView;
