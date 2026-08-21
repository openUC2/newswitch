import { authFrame, WS_UNAUTHORIZED_CLOSE_CODE } from "@/lib/auth/authFetch";
import { clearToken } from "@/lib/auth/token";
import { ZSTD_STREAM_PATH } from "@/constants";
import type { Detector } from "@/apps/default/hooks/actions";
import { decompress } from "fzstd";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { DataTexture, LinearFilter, RedFormat, UnsignedByteType } from "three";

type StreamStats = {
  bytesReceived: number;
  chunksReceived: number;
};

export const useZstdLiveTexture = ({
  url = ZSTD_STREAM_PATH,
  detector,
  setStats,
}: {
  url?: string;
  detector: Detector;
  // The stream handler below calls this with an updater function, so it needs the
  // React state-setter shape, not a plain `(stats) => void`.
  setStats?: Dispatch<SetStateAction<StreamStats>>;
}) => {
  const [connectionState, setConnectionState] = useState("connecting");

  // Kept in a ref so that an unmemoized `setStats` prop does not tear down and
  // re-open the websocket on every render.
  const setStatsRef = useRef(setStats);
  useEffect(() => {
    setStatsRef.current = setStats;
  }, [setStats]);

  // Create a persistent DataTexture
  const texture = useMemo(() => {
    // For single channel 16-bit, we use RedFormat + UnsignedShortType
    // For 8-bit, use RedFormat + UnsignedByteType
    const format = RedFormat;
    const type = UnsignedByteType;
    console.log("Creating texture with format:", format, "and type:", type);

    const tex = new DataTexture(
      new Uint8Array((detector.width || 1024) * (detector.height || 1024)), // Placeholder data array
      detector.width || 1024,
      detector.height || 1024,
      format,
      type,
    );
    tex.magFilter = LinearFilter;
    tex.minFilter = LinearFilter;
    return tex;
  }, [detector]);

  useEffect(() => {
    const socket = new WebSocket(`${url}/${detector.slot}`);
    socket.binaryType = "arraybuffer";

    socket.onmessage = (event: MessageEvent) => {
      try {
        const compressed = new Uint8Array(event.data as ArrayBuffer);
        const decompressed = decompress(compressed);

        if (!texture.image.data) return;
        // Update texture image data
        // We cast to the correct typed array based on our bit depth
        setStatsRef.current?.((prev) => ({
          bytesReceived: prev.bytesReceived + compressed.byteLength,
          chunksReceived: prev.chunksReceived + 1,
        }));
        texture.image.data.set(decompressed);

        texture.needsUpdate = true;
      } catch (err) {
        console.error("Zstd Decompression Error:", err);
      }
    };

    socket.onopen = () => {
      // In-band auth: a WebSocket cannot carry an Authorization header.
      socket.send(JSON.stringify(authFrame()));
      setConnectionState("connected");
    };
    socket.onerror = () => setConnectionState("error");
    socket.onclose = (event) => {
      if (event.code === WS_UNAUTHORIZED_CLOSE_CODE) clearToken();
      setConnectionState("disconnected");
    };

    return () => socket.close();
  }, [url, detector.slot, texture]);

  return { texture, connectionState };
};
