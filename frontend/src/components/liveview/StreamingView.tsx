import { authFrame, WS_UNAUTHORIZED_CLOSE_CODE } from "@/lib/auth/authFetch";
import { clearToken } from "@/lib/auth/token";
import JMuxer from "jmuxer";
import React, { useCallback, useEffect, useRef, useState } from "react";

// --- Types for JMuxer (since it lacks official types) ---
interface JMuxerOptions {
  node: HTMLVideoElement;
  mode: "video" | "audio" | "both";
  flushingTime?: number;
  fps?: number;
  debug?: boolean;
  clearBuffer?: boolean;
  onReady?: () => void;
  // jmuxer ships no types; its error payload is untyped, so treat it as opaque.
  onError?: (data: unknown) => void;
}

interface JMuxerInput {
  video?: Uint8Array;
  audio?: Uint8Array;
  duration?: number;
}

interface JMuxerInstance {
  feed(data: JMuxerInput): void;
  destroy(): void;
}
// -------------------------------------------------------

type ConnectionState = "disconnected" | "connecting" | "connected" | "error";

interface LiveViewProps {
  /** WebSocket URL for the video stream */
  url?: string;
  /** Auto-reconnect on disconnect */
  autoReconnect?: boolean;
  /** Reconnect delay in milliseconds */
  reconnectDelay?: number;
  /** Maximum reconnect attempts (0 = infinite) */
  maxReconnectAttempts?: number;
  /** Optional capture button callback */
  onCapture?: () => void;
  /** Whether capture is in progress */
  isCapturing?: boolean;
  /** Whether capture is disabled/locked */
  isCaptureDisabled?: boolean;
  /** Custom class name for container */
  className?: string;
}

export const StreamingView: React.FC<LiveViewProps> = ({
  url = import.meta.env.VITE_WEBSOCKET_URL + "/video",
  autoReconnect = true,
  reconnectDelay = 2000,
  maxReconnectAttempts = 5,
  onCapture,
  isCapturing = false,
  isCaptureDisabled = false,
  className,
}) => {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const jmuxerRef = useRef<JMuxerInstance | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const isCleaningUpRef = useRef(false);

  const [connectionState, setConnectionState] =
    useState<ConnectionState>("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState({ bytesReceived: 0, chunksReceived: 0 });

  // Forward declaration for connect to allow mutual references
  const connectRef = useRef<() => void>(() => {});

  // Cleanup function
  const cleanup = useCallback(() => {
    isCleaningUpRef.current = true;

    // Clear reconnect timeout
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Close WebSocket
    if (socketRef.current) {
      socketRef.current.onopen = null;
      socketRef.current.onmessage = null;
      socketRef.current.onerror = null;
      socketRef.current.onclose = null;
      if (
        socketRef.current.readyState === WebSocket.OPEN ||
        socketRef.current.readyState === WebSocket.CONNECTING
      ) {
        socketRef.current.close();
      }
      socketRef.current = null;
    }

    // Destroy JMuxer instance
    if (jmuxerRef.current) {
      try {
        jmuxerRef.current.destroy();
      } catch (e) {
        console.error("Error destroying JMuxer:", e);
      }
      jmuxerRef.current = null;
    }

    // Clear video source
    if (videoRef.current) {
      videoRef.current.src = "";
      videoRef.current.load();
    }

    isCleaningUpRef.current = false;
  }, []);

  // Connect to WebSocket and set up JMuxer
  const connect = useCallback(() => {
    if (isCleaningUpRef.current) return;
    if (!videoRef.current) return;

    setConnectionState("connecting");
    setError(null);

    try {
      // 1. Initialize JMuxer.
      // jmuxer's shipped constructor signature does not match the options it actually
      // accepts, so re-describe it with the JMuxerOptions declared above rather than
      // reaching for `any`.
      const JMuxerCtor = JMuxer as unknown as new (
        options: JMuxerOptions,
      ) => JMuxerInstance;

      jmuxerRef.current = new JMuxerCtor({
        node: videoRef.current,
        mode: "video",
        flushingTime: 0, // 0 = Immediate playback for lowest latency
        fps: 30, // Must match server FPS
        debug: false,
        clearBuffer: true,
        onError: (data: unknown) => {
          console.error("JMuxer error:", data);
          // If buffer is broken, we might want to force a reconnect
          if (String(data).includes("Invalid NAL unit")) {
            // Optional: Handle corruption
          }
        },
      } as JMuxerOptions);

      // 2. Connect WebSocket
      const socket = new WebSocket(url);
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;

      socket.onopen = () => {
        if (isCleaningUpRef.current) return;
        // In-band auth: a WebSocket cannot carry an Authorization header.
        socket.send(JSON.stringify(authFrame()));
        console.log("Video stream connected");
        setConnectionState("connected");
        reconnectAttemptsRef.current = 0;
        setStats({ bytesReceived: 0, chunksReceived: 0 });
      };

      socket.onmessage = (event: MessageEvent) => {
        if (isCleaningUpRef.current) return;

        // Feed raw binary data directly to JMuxer
        if (jmuxerRef.current) {
          const data = new Uint8Array(event.data as ArrayBuffer);

          setStats((prev) => ({
            bytesReceived: prev.bytesReceived + data.byteLength,
            chunksReceived: prev.chunksReceived + 1,
          }));

          jmuxerRef.current.feed({
            video: data,
          });
        }
      };

      socket.onerror = (event) => {
        console.error("WebSocket error:", event);
        setError("WebSocket connection error");
        setConnectionState("error");
      };

      socket.onclose = (event) => {
        if (isCleaningUpRef.current) return;

        console.log("Video stream disconnected:", event.code, event.reason);
        setConnectionState("disconnected");

        // Not transient - reconnecting with the same rejected token would loop.
        if (event.code === WS_UNAUTHORIZED_CLOSE_CODE) {
          clearToken();
          return;
        }

        // Handle reconnection
        if (
          autoReconnect &&
          (maxReconnectAttempts === 0 ||
            reconnectAttemptsRef.current < maxReconnectAttempts)
        ) {
          reconnectAttemptsRef.current++;
          console.log(
            `Reconnecting... Attempt ${reconnectAttemptsRef.current}`,
          );

          reconnectTimeoutRef.current = setTimeout(() => {
            cleanup();
            connectRef.current();
          }, reconnectDelay);
        }
      };
    } catch (err) {
      console.error("Error setting up stream:", err);
      setError(
        err instanceof Error ? err.message : "Failed to set up video stream",
      );
      setConnectionState("error");
    }
  }, [url, autoReconnect, reconnectDelay, maxReconnectAttempts, cleanup]);

  // Keep connectRef updated
  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  // Manual reconnect handler
  const handleReconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    cleanup();
    setTimeout(() => connectRef.current(), 100);
  }, [cleanup]);

  // Initialize connection on mount
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      connectRef.current();
    }, 0);

    return () => {
      clearTimeout(timeoutId);
      cleanup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Format bytes for display
  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  };

  return (
    <div className={`relative w-full h-full ${className || ""}`}>
      {/* Video element - fills container */}
      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-contain bg-black"
        autoPlay
        muted
        playsInline
      />

      {/* Connection status badge */}
      <div className="absolute top-2 right-2 flex items-center gap-2 text-xs bg-black/60 px-2 py-1 rounded">
        <div
          className={`w-2 h-2 rounded-full ${
            connectionState === "connected"
              ? "bg-green-500"
              : connectionState === "connecting"
                ? "bg-yellow-500 animate-pulse"
                : connectionState === "error"
                  ? "bg-red-500"
                  : "bg-gray-500"
          }`}
        />
        <span className="text-white/80 capitalize">{connectionState}</span>
        {connectionState === "connected" && (
          <span className="text-white/50">
            {formatBytes(stats.bytesReceived)}
          </span>
        )}
      </div>

      {/* Capture button */}
      {onCapture && connectionState === "connected" && (
        <button
          onClick={onCapture}
          disabled={isCapturing || isCaptureDisabled}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 disabled:bg-white/5 disabled:cursor-not-allowed text-white rounded-full backdrop-blur-sm border border-white/20 transition-all"
        >
          <svg
            className="w-5 h-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"
            />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"
            />
          </svg>
          {isCapturing ? "Capturing..." : "Capture"}
        </button>
      )}

      {/* Overlay for disconnected state */}
      {connectionState !== "connected" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/70">
          {connectionState === "connecting" && (
            <div className="flex flex-col items-center gap-2">
              <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
              <span className="text-white text-sm">
                Connecting to stream...
              </span>
            </div>
          )}
          {(connectionState === "disconnected" ||
            connectionState === "error") && (
            <div className="flex flex-col items-center gap-3">
              {error && (
                <span className="text-red-400 text-sm max-w-xs text-center">
                  {error}
                </span>
              )}
              <button
                onClick={handleReconnect}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
              >
                Reconnect
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default StreamingView;
