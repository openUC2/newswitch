import { authFrame, WS_UNAUTHORIZED_CLOSE_CODE } from "@/lib/auth/authFetch";
import { clearToken } from "@/lib/auth/token";
import { H264_STREAM_PATH } from "@/constants";
import type { Detector } from "@/apps/default/hooks/actions";
import { useFrame } from "@react-three/fiber";
import JMuxer from "jmuxer";
import { useEffect, useMemo, useRef, useState } from "react";
import { LinearFilter, SRGBColorSpace, VideoTexture } from "three";

type ConnectionState = "disconnected" | "connecting" | "connected" | "error";

type StreamStats = {
  bytesReceived: number;
  chunksReceived: number;
};

interface JMuxerInstance {
  feed(data: { video: Uint8Array }): void;
  destroy(): void;
}

export const useH264LiveTexture = ({
  url = H264_STREAM_PATH,
  detector,
  setStats,
}: {
  url?: string;
  detector: Detector;
  setStats?: (stats: StreamStats) => void;
}) => {
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("connecting");

  // Kept in a ref so that an unmemoized `setStats` prop does not tear down and
  // re-open the websocket on every render.
  const setStatsRef = useRef(setStats);
  useEffect(() => {
    setStatsRef.current = setStats;
  }, [setStats]);

  const socketRef = useRef<WebSocket | null>(null);
  const jmuxerRef = useRef<JMuxerInstance | null>(null);
  const statsRef = useRef<StreamStats>({ bytesReceived: 0, chunksReceived: 0 });

  const videoElement = useMemo(() => {
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.autoplay = true;
    // Optimization for stream lag
    video.setAttribute("webkit-playsinline", "webkit-playsinline");
    return video;
  }, []);

  const texture = useMemo(() => {
    const videoTexture = new VideoTexture(videoElement);
    videoTexture.colorSpace = SRGBColorSpace;
    videoTexture.magFilter = LinearFilter;
    videoTexture.minFilter = LinearFilter;
    videoTexture.generateMipmaps = false;
    return videoTexture;
  }, [videoElement]);

  useEffect(() => {
    try {
      jmuxerRef.current = new JMuxer({
        node: videoElement,
        mode: "video",
        flushingTime: 0,
        fps: 30,
        debug: false,
        clearBuffer: true,
      });

      const socket = new WebSocket(`${url}/${detector.slot}`);
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;

      socket.onopen = () => {
        // These sockets authenticate in band: browsers cannot set headers on a
        // WebSocket, and a query-string token would land in every access log.
        socket.send(JSON.stringify(authFrame()));
        setConnectionState("connected");
      };
      socket.onmessage = (event: MessageEvent) => {
        const chunk = new Uint8Array(event.data as ArrayBuffer);
        statsRef.current = {
          bytesReceived: statsRef.current.bytesReceived + chunk.byteLength,
          chunksReceived: statsRef.current.chunksReceived + 1,
        };
        setStatsRef.current?.({ ...statsRef.current });
        jmuxerRef.current?.feed({ video: chunk });
      };
      socket.onerror = () => setConnectionState("error");
      socket.onclose = (event) => {
        if (event.code === WS_UNAUTHORIZED_CLOSE_CODE) clearToken();
        setConnectionState("disconnected");
      };
    } catch (error) {
      console.error("[Stage] Failed to initialize live stream", error);
    }

    return () => {
      socketRef.current?.close();
      jmuxerRef.current?.destroy();
      videoElement.pause();
      videoElement.src = "";
      videoElement.load();
    };
    // NOTE: `detector.slot` is part of the websocket URL, so it must be a dependency -
    // without it, switching detectors kept the socket pointed at the old slot.
    // `setStats` is deliberately read through a ref (see above) instead of being a
    // dependency, so an unmemoized setter cannot cause a reconnect loop.
  }, [url, videoElement, detector.slot]);

  // VideoTextures fed by JMuxer sometimes need the update flag set manually. This lives
  // here (rather than in the consumer's useFrame) because the texture is owned by this hook.
  // Held in a ref because react-hooks/immutability forbids mutating a memoized value
  // directly; the ref is the sanctioned mutable handle to the texture we own.
  const textureRef = useRef(texture);
  useEffect(() => {
    textureRef.current = texture;
  }, [texture]);

  useFrame(() => {
    textureRef.current.needsUpdate = true;
  });

  return { texture, connectionState };
};
